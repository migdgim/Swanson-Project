"""Estrazione dei descrittori MeSH da un record PubMed cacheato.

I record grezzi conservano i *nomi* dei descrittori (`DescriptorName`); gli UI code
MeSH (D...) si perdono nel parsing Entrez, quindi i nodi del grafo sono name-based.
Per il verdetto S1/S2 e' sufficiente e coerente; gli ID aperti servono solo in
pubblicazione (S4), dove verranno rimappati.
"""

from __future__ import annotations

from typing import Any


def descriptors(raw_article: dict[str, Any]) -> set[str]:
    """Insieme dei nomi-descrittore MeSH di un articolo (senza qualifier)."""
    out: set[str] = set()
    citation = raw_article.get("MedlineCitation")
    if not isinstance(citation, dict):
        return out
    headings = citation.get("MeshHeadingList")
    if not isinstance(headings, list):
        return out
    for h in headings:
        if not isinstance(h, dict):
            continue
        name = h.get("DescriptorName")
        if name:
            out.add(str(name))
    return out
