"""Closed discovery ABC: dati i corridoi A e C, trova i B sul cammino A-B-C.

Test di sanita' del sistema (gate S1): il sistema deve ritrovare i B *gia' noti*
(config `known_b_terms`). Se ne ritrova < 5 su 7, la pipeline e' rotta: fermarsi.

Il filtro preliminare (df) e' il cuore del valore: scarta i descrittori troppo rari
(rumore da singolo paper) e quelli troppo generici (check-tag MeSH: Humans, Animals...
— le "stopword di dominio" che generano co-occorrenze spurie).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx

from graph.build_graph import NODE_A, NODE_C


@dataclass
class BCandidate:
    label: str
    a_df: int
    c_df: int
    total_df: int
    score: float
    rank: int = 0


def closed_discovery(graph: nx.Graph, ranking_cfg: dict[str, Any]) -> list[BCandidate]:
    """B candidati che collegano A e C, filtrati per document-frequency e ordinati.

    Score di linking: (a_df * c_df) / total_df — premia i termini condivisi e bilanciati
    tra i due corridoi, penalizza gli ubiqui. E' una metrica di partenza; il confronto
    TF-IDF vs PMI (config `ranking.metrics`) e' tarato sul DEV set in S2.
    """
    df_min = int(ranking_cfg["df_min"])
    df_max_ratio = float(ranking_cfg["df_max_ratio"])
    total_papers = int(graph.graph["total_papers"])
    df_max = df_max_ratio * total_papers

    candidates: list[BCandidate] = []
    a_neighbors = set(graph.neighbors(NODE_A))
    c_neighbors = set(graph.neighbors(NODE_C))
    for node in a_neighbors & c_neighbors:
        if node in (NODE_A, NODE_C):
            continue
        data = graph.nodes[node]
        a_df = int(data["a_df"])
        c_df = int(data["c_df"])
        total_df = int(data["total_df"])
        if total_df < df_min or total_df > df_max:
            continue
        score = (a_df * c_df) / total_df
        candidates.append(BCandidate(str(node), a_df, c_df, total_df, score))

    candidates.sort(key=lambda b: (-b.score, -min(b.a_df, b.c_df), b.label))
    for i, b in enumerate(candidates, start=1):
        b.rank = i
    return candidates


@dataclass
class KnownBHit:
    label: str
    matched_descriptor: str | None
    rank: int | None


def known_b_gate(
    candidates: list[BCandidate], known_b_terms: list[dict[str, Any]]
) -> tuple[list[KnownBHit], int]:
    """Verifica quanti B noti sono stati ritrovati tra i candidati. I `hint` del config
    elencano i nomi-descrittore MeSH (separati da ';') di ciascun B noto."""
    by_label = {c.label: c for c in candidates}
    hits: list[KnownBHit] = []
    found = 0
    for term in known_b_terms:
        label = str(term["label"])
        descs = [d.strip() for d in str(term.get("hint", "")).split(";") if d.strip()]
        best: KnownBHit | None = None
        for d in descs:
            cand = by_label.get(d)
            if cand is not None and (best is None or best.rank is None
                                     or (cand.rank < best.rank)):
                best = KnownBHit(label, d, cand.rank)
        if best is not None:
            found += 1
            hits.append(best)
        else:
            hits.append(KnownBHit(label, None, None))
    return hits, found
