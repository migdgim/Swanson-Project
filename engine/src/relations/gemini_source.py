"""`RelationSource` LLM grounded su Google Gemini.

Determinismo: temperatura 0, ogni risposta cacheata su disco (`llm_extractions`, chiave
sul prompt+modello) → re-run offline. Guardrail nel prompt (`prompt.py`): solo estrazione,
mai giudizio di plausibilità.

Dipendenza: `google-generativeai` (approvata dal committente). Il pacchetto è deprecato a
favore di `google-genai`: migrazione da valutare, ma la firma qui usata è stabile.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import google.generativeai as genai

from ingest.cache import Cache

from .base import ExtractionResult, Relation, Usage
from .prompt import PROMPT_VERSION, build_prompt


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_fences(text: str) -> str:
    """Rimuove eventuali ```json ... ``` difensivamente (non atteso con response_mime_type)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def _parse_relations(text: str, pmid: str) -> tuple[list[dict[str, str]], bool]:
    """Estrae la lista `relations` dal JSON del modello. (relazioni, parse_ok)."""
    try:
        obj = json.loads(_strip_fences(text))
    except (json.JSONDecodeError, ValueError):
        return [], False
    rels = obj.get("relations") if isinstance(obj, dict) else None
    if not isinstance(rels, list):
        return [], False
    out: list[dict[str, str]] = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        subj = str(r.get("subject", "")).strip()
        pred = str(r.get("predicate", "")).strip()
        obj_ = str(r.get("object", "")).strip()
        ev = str(r.get("evidence", "")).strip()
        if subj and pred and obj_:
            out.append({"subject": subj, "predicate": pred, "object": obj_, "evidence": ev})
    return out, True


def _result_from_payload(pmid: str, payload: dict[str, Any], *, cached: bool) -> ExtractionResult:
    u = payload.get("usage", {}) or {}
    usage = Usage(
        prompt_tokens=int(u.get("prompt_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        total_tokens=int(u.get("total_tokens", 0) or 0),
    )
    rels = [
        Relation(
            subject=r["subject"],
            predicate=r["predicate"],
            object=r["object"],
            pmid=pmid,
            evidence=r.get("evidence", ""),
        )
        for r in payload.get("relations", [])
        if isinstance(r, dict) and r.get("subject") and r.get("predicate") and r.get("object")
    ]
    return ExtractionResult(
        pmid=pmid,
        relations=rels,
        usage=usage,
        cached=cached,
        parse_ok=bool(payload.get("parse_ok", True)),
    )


class GeminiRelationSource:
    """Estrazione grounded via Gemini, con cache su disco e rate limiting free-tier."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        cache: Cache,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
        rate_per_min: int = 15,
    ) -> None:
        self._model_name = model
        self._cache = cache
        self._temperature = float(temperature)
        self._max_output_tokens = int(max_output_tokens)
        self._min_interval = 60.0 / rate_per_min if rate_per_min > 0 else 0.0
        self._last_call = 0.0
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def _prompt_hash(self, prompt: str) -> str:
        h = hashlib.sha256()
        for part in (self._model_name, PROMPT_VERSION, f"t={self._temperature}", prompt):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def extract(self, *, pmid: str, title: str | None, abstract: str) -> ExtractionResult:
        """Estrae le relazioni da un abstract. Cache-first; su miss chiama l'API (temp 0)."""
        prompt = build_prompt(title, abstract)
        ph = self._prompt_hash(prompt)
        cached = self._cache.get_llm_extraction(prompt_hash=ph, model=self._model_name)
        if cached is not None:
            return _result_from_payload(pmid, json.loads(cached), cached=True)

        self._throttle()
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "temperature": self._temperature,
                "max_output_tokens": self._max_output_tokens,
                "response_mime_type": "application/json",
            },
        )
        try:
            text = resp.text or ""
        except (ValueError, AttributeError):
            # es. risposta bloccata da safety: nessun testo. Registriamo l'evento onestamente.
            text = ""
        um = getattr(resp, "usage_metadata", None)
        usage = {
            "prompt_tokens": int(getattr(um, "prompt_token_count", 0) or 0),
            "output_tokens": int(getattr(um, "candidates_token_count", 0) or 0),
            "total_tokens": int(getattr(um, "total_token_count", 0) or 0),
        }
        relations, parse_ok = _parse_relations(text, pmid)
        payload: dict[str, Any] = {
            "prompt_version": PROMPT_VERSION,
            "model": self._model_name,
            "relations": relations,
            "usage": usage,
            "parse_ok": parse_ok,
        }
        self._cache.put_llm_extraction(
            pmid=pmid,
            model=self._model_name,
            prompt_hash=ph,
            response_json=json.dumps(payload, ensure_ascii=False),
            created_at=_utc_now_iso(),
        )
        return _result_from_payload(pmid, payload, cached=False)

    def relations_for(self, pmids: list[str]) -> Iterable[Relation]:
        """Implementa il Protocol: relazioni per una lista di PMID (via cache dei paper)."""
        for pmid in pmids:
            text = self._cache.get_paper_text(pmid)
            if text is None:
                continue
            title, abstract = text
            if not abstract:
                continue
            yield from self.extract(pmid=pmid, title=title, abstract=abstract).relations
