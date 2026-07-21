"""Sinonimi/entry-terms MeSH per descrittore, via E-utilities (db=mesh), cacheati.

Serve a chiudere il gap abbreviazioni della normalizzazione: l'LLM estrae "TNF-alpha",
il descrittore MeSH è "Tumor Necrosis Factor-alpha". Recuperando gli entry-terms del
descrittore (che includono "TNF-alpha", "TNF") il match riesce, **senza** cambiare lo
spazio nodi (restano descrittori MeSH: confronto S2 pulito).

Determinismo: risposta grezza in `eutils_cache`, sinonimi parsati in `mesh_synonyms`.
Re-run offline. Nessuna dipendenza nuova (Bio.Entrez già presente).
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, cast

from Bio import Entrez

from ingest.cache import Cache


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class MeshSynonymSource:
    """Fornisce le forme superficiali (descrittore + entry-terms) di un descrittore MeSH."""

    def __init__(self, *, api_key: str, email: str, cache: Cache, tool: str = "swanson-lbd") -> None:
        if not api_key or not email:
            raise ValueError("NCBI_API_KEY/NCBI_EMAIL richiesti per db=mesh.")
        Entrez.email = email
        Entrez.api_key = api_key
        Entrez.tool = tool
        self._cache = cache

    def synonyms_for(self, descriptor: str) -> list[str]:
        """Forme del descrittore (incluso se stesso). Cache-first; su miss interroga MeSH."""
        cached = self._cache.get_mesh_synonyms(descriptor)
        if cached is not None:
            return cached
        forms = self._fetch(descriptor)
        # garantisce il descrittore stesso e deduplica preservando l'ordine
        seen: set[str] = set()
        out: list[str] = []
        for f in [descriptor, *forms]:
            f = f.strip()
            if f and f.lower() not in seen:
                seen.add(f.lower())
                out.append(f)
        self._cache.put_mesh_synonyms(descriptor, out, _utc_now_iso())
        return out

    def _fetch(self, descriptor: str) -> list[str]:
        uid = self._search_uid(descriptor)
        if uid is None:
            return []
        return self._summary_terms(uid)

    def _search_uid(self, descriptor: str) -> str | None:
        params = {"db": "mesh", "term": f'"{descriptor}"[MeSH Terms]', "retmax": 1}
        handle = Entrez.esearch(**params)
        try:
            rec = cast("dict[str, Any]", _to_plain(Entrez.read(handle)))
        finally:
            handle.close()
        ids = rec.get("IdList", [])
        return str(ids[0]) if ids else None

    def _summary_terms(self, uid: str) -> list[str]:
        handle = Entrez.esummary(db="mesh", id=uid)
        try:
            raw = handle.read()
        finally:
            handle.close()
        data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        rec = _to_plain(Entrez.read(io.BytesIO(data)))
        docs = rec if isinstance(rec, list) else [rec]
        terms: list[str] = []
        for d in docs:
            if not isinstance(d, dict):
                continue
            ds = d.get("DS_MeshTerms")
            if isinstance(ds, list):
                terms += [str(t) for t in ds]
        return terms
