"""Test della closed discovery e del gate B noti (offline, deterministici).

Usano grafi sintetici e una mini-cache SQLite in memoria: nessuna rete.
"""

from __future__ import annotations

import networkx as nx

from discovery.closed_discovery import closed_discovery, known_b_gate
from graph.build_graph import NODE_A, NODE_C


def _graph(bs: list[tuple[str, int, int, int]], total_papers: int) -> nx.Graph:
    """bs: (label, a_df, c_df, total_df). Costruisce il grafo A-B-C minimo."""
    g: nx.Graph = nx.Graph()
    g.add_node(NODE_A, kind="anchor", df=100)
    g.add_node(NODE_C, kind="anchor", df=100)
    g.graph["total_papers"] = total_papers
    for label, a_df, c_df, total_df in bs:
        g.add_node(label, kind="mesh", a_df=a_df, c_df=c_df, total_df=total_df)
        if a_df:
            g.add_edge(NODE_A, label, weight=a_df)
        if c_df:
            g.add_edge(label, NODE_C, weight=c_df)
    return g


RANKING = {"df_min": 5, "df_max_ratio": 0.25}


def test_requires_link_to_both_corridors() -> None:
    # 'OnlyA' tocca solo A, 'OnlyC' solo C: nessuno dei due e' un B valido.
    g = _graph([("Good", 10, 10, 20), ("OnlyA", 10, 0, 10), ("OnlyC", 0, 10, 10)], 1000)
    labels = {b.label for b in closed_discovery(g, RANKING)}
    assert labels == {"Good"}


def test_df_min_filters_rare() -> None:
    g = _graph([("Rare", 2, 2, 4), ("Keep", 5, 5, 10)], 1000)
    labels = {b.label for b in closed_discovery(g, RANKING)}
    assert labels == {"Keep"}


def test_df_max_ratio_filters_generic() -> None:
    # total_df 300 > 0.25*1000 = 250 -> scartato come stopword di dominio.
    g = _graph([("Generic", 150, 150, 300), ("Specific", 20, 20, 40)], 1000)
    labels = {b.label for b in closed_discovery(g, RANKING)}
    assert labels == {"Specific"}


def test_ranking_prefers_balanced_specific() -> None:
    g = _graph([("Bal", 20, 20, 40), ("Skewed", 39, 1, 40)], 1000)
    ranked = closed_discovery(g, RANKING)
    assert ranked[0].label == "Bal"  # score 10.0 > 0.975
    assert ranked[0].rank == 1


def test_known_b_gate_counts_and_matches() -> None:
    g = _graph([("Interleukin-6", 20, 20, 40), ("Butyrates", 8, 8, 16)], 1000)
    cands = closed_discovery(g, RANKING)
    known = [
        {"label": "IL-6", "hint": "Interleukin-6"},
        {"label": "SCFA", "hint": "Butyrates; Fatty Acids, Volatile"},
        {"label": "assente", "hint": "Nonexistent Descriptor"},
    ]
    hits, found = known_b_gate(cands, known)
    assert found == 2
    by_label = {h.label: h for h in hits}
    assert by_label["IL-6"].matched_descriptor == "Interleukin-6"
    assert by_label["SCFA"].matched_descriptor == "Butyrates"
    assert by_label["assente"].rank is None
