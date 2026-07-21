"""Normalizzazione delle menzioni estratte dall'LLM ai descrittori MeSH.

Scelta committente (2026-07-21): mappare le menzioni (testo libero: soggetto/oggetto
delle triple) ai **descrittori MeSH già presenti nel grafo**. Vantaggio: il test S2
confronta lo stesso spazio di nodi B, cambiando solo la definizione dell'arco
(co-occorrenza vs relazione esplicita) — confronto pulito.

Il match è **a stringhe, offline, deterministico**, quindi *lossy* (plurali, abbreviazioni
come "IL-6" vs "Interleukin-6"). La copertura va misurata e riportata onestamente
(`coverage_report.py`); una copertura bassa è un risultato, non un bug da mascherare.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")


def _stem(tok: str) -> str:
    """Stemming minimale: toglie la 's' finale dei plurali (butyrates -> butyrate)."""
    return tok[:-1] if len(tok) > 3 and tok.endswith("s") else tok


def _tokens(s: str) -> list[str]:
    return [_stem(t) for t in _WORD.findall(s.lower())]


def descriptor_in_mentions(descriptor: str, mention_texts: list[str]) -> bool:
    """True se il descrittore MeSH è menzionato in almeno una relazione.

    Match (dopo lowercase, stemming plurale, tokenizzazione):
    - substring esatto normalizzato del descrittore nella menzione, OPPURE
    - tutti i token del descrittore presenti nei token della menzione.
    """
    d_tokens = _tokens(descriptor)
    if not d_tokens:
        return False
    d_join = " ".join(d_tokens)
    d_set = set(d_tokens)
    for text in mention_texts:
        m_tokens = _tokens(text)
        if not m_tokens:
            continue
        if d_join in " ".join(m_tokens):
            return True
        if d_set <= set(m_tokens):
            return True
    return False


def descriptor_forms_in_mentions(forms: list[str], mention_texts: list[str]) -> bool:
    """True se una qualunque forma (descrittore o suo sinonimo MeSH) è menzionata."""
    return any(descriptor_in_mentions(f, mention_texts) for f in forms)


def _relation_texts(relations: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for r in relations:
        if isinstance(r, dict):
            texts.append(str(r.get("subject", "")))
            texts.append(str(r.get("object", "")))
    return texts


def supported_descriptors(
    paper_descriptors: set[str],
    relations: list[dict[str, Any]],
    synonyms_of: Callable[[str], list[str]] | None = None,
) -> set[str]:
    """Sottoinsieme dei descrittori MeSH del paper che compaiono in una relazione estratta.

    Se `synonyms_of` è fornito, per ogni descrittore si prova anche l'insieme dei suoi
    entry-terms MeSH (chiude il gap abbreviazioni: es. "TNF-alpha" -> descrittore).
    """
    texts = _relation_texts(relations)
    out: set[str] = set()
    for d in paper_descriptors:
        forms = synonyms_of(d) if synonyms_of is not None else [d]
        if descriptor_forms_in_mentions(forms, texts):
            out.add(d)
    return out
