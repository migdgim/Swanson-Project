"""Test della logica open discovery (mezzo-ponte -> chiusura), offline."""

from __future__ import annotations

import networkx as nx

from validation.time_slicing import build_open_slices, evaluate_open_split

RANKING = {"df_min": 1, "df_max_ratio": 1.0, "top_k": [10]}


def _add_b(g: nx.Graph, name: str, a_years: list[int], c_years: list[int]) -> None:
    g.add_node(name, kind="mesh", label=name)
    if a_years:
        g.add_edge("A", name, years=sorted(a_years))
    if c_years:
        g.add_edge(name, "C", years=sorted(c_years))


def _graph() -> nx.Graph:
    g: nx.Graph = nx.Graph()
    g.add_node("A", kind="anchor")
    g.add_node("C", kind="anchor")
    # B_open: solo lato A pre-cutoff (2010), acquisisce C nel post (2020) -> candidato + hit.
    _add_b(g, "B_open", a_years=[2010], c_years=[2020])
    # B_bridge: già ponte pre-cutoff (A e C entrambi <=2015) -> NON candidato open.
    _add_b(g, "B_bridge", a_years=[2008], c_years=[2009])
    # B_stuck: solo lato A, non acquisisce mai C -> candidato ma non hit.
    _add_b(g, "B_stuck", a_years=[2011], c_years=[])
    return g


def test_open_candidate_and_hit_logic() -> None:
    g = _graph()
    cutoff, window = 2015, (2016, 2025)
    slices = build_open_slices(g, cutoff, window, n_pre_a=10, n_pre_c=10,
                               ranking_cfg=RANKING, grounded_years=None)
    labels = {s.label for s in slices}
    # Solo i 'mezzo-ponte' pre-cutoff sono candidati; B_bridge (2 lati) è escluso.
    assert labels == {"B_open", "B_stuck"}

    by = {s.label: s for s in slices}
    assert by["B_open"].present == "A"
    assert by["B_open"].absent_post == 1 and by["B_open"].is_hit(1)
    assert by["B_stuck"].absent_post == 0 and not by["B_stuck"].is_hit(1)


def test_open_grounded_score_from_evidence() -> None:
    g = _graph()
    # Evidenza grounded sul lato A solo per B_open (anno 2010) -> grounded_score=1 vs 0.
    grounded_years = {"B_open": ([2010], []), "B_stuck": ([], [])}
    ev = evaluate_open_split(g, "dev", 2015, (2016, 2025), 10, 10, 1, RANKING, 42,
                             grounded_years)
    assert ev.n_candidates == 2 and ev.n_hits == 1
    # grounded mette B_open (l'unico con evidenza) in cima -> P@10 include l'hit.
    assert ev.methods["grounded"].precision_at[10] == 1 / 10
    assert set(ev.methods) == {"grounded", "frequency", "random"}
