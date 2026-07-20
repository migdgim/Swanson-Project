"""Test della meccanica di time-slicing (offline, deterministica).

Verificano il conteggio pre/post sugli anni, la definizione di hit e il calcolo
di precision/recall. Non giudicano la *bonta'* della metrica (quello e' il verdetto
scientifico, riportato dal runner), solo che i conteggi siano corretti.
"""

from __future__ import annotations

import networkx as nx

from graph.build_graph import NODE_A, NODE_C
from validation.time_slicing import BSlice, build_slices, evaluate_split

RANKING = {"df_min": 1, "df_max_ratio": 1.0, "top_k": [10]}


def _g(bs: list[tuple[str, list[int], list[int]]]) -> nx.Graph:
    g: nx.Graph = nx.Graph()
    g.add_node(NODE_A, kind="anchor")
    g.add_node(NODE_C, kind="anchor")
    for label, ay, cy in bs:
        g.add_node(label, kind="mesh")
        if ay:
            g.add_edge(NODE_A, label, years=sorted(ay))
        if cy:
            g.add_edge(label, NODE_C, years=sorted(cy))
    return g


def test_pre_post_counts() -> None:
    g = _g([("B", [2005, 2009, 2012], [2010, 2013])])
    slices = build_slices(g, cutoff=2010, window=(2011, 2015), n_pre_a=100, n_pre_c=100,
                          ranking_cfg=RANKING)
    assert len(slices) == 1
    s = slices[0]
    assert s.a_pre == 2 and s.c_pre == 1     # <=2010
    assert s.a_post == 1 and s.c_post == 1   # in [2011,2015]


def test_candidate_requires_both_corridors_pre_cutoff() -> None:
    # c compare solo nel 2013 (> cutoff) -> c_pre=0 -> non e' candidato.
    g = _g([("B", [2005], [2013])])
    slices = build_slices(g, cutoff=2010, window=(2011, 2015), n_pre_a=100, n_pre_c=100,
                          ranking_cfg=RANKING)
    assert slices == []


def test_hit_threshold_requires_both_sides() -> None:
    b = BSlice("x", a_pre=1, c_pre=1, a_post=2, c_post=1)
    assert b.is_hit(1) is True
    assert b.is_hit(2) is False  # c_post=1 < 2


def test_evaluate_split_precision_bounds() -> None:
    g = _g([
        ("H1", [2008, 2009], [2009, 2010]),   # hit: post su entrambi
        ("H2", [2007], [2010]),               # hit debole
        ("Miss", [2006], [2008]),             # nessun post
    ])
    # aggiungo post-cutoff a H1/H2
    g[NODE_A]["H1"]["years"] = [2008, 2009, 2013]
    g["H1"][NODE_C]["years"] = [2009, 2010, 2014]
    g[NODE_A]["H2"]["years"] = [2007, 2012]
    g["H2"][NODE_C]["years"] = [2010, 2013]
    ev = evaluate_split(g, "dev", cutoff=2010, window=(2011, 2015),
                        n_pre_a=100, n_pre_c=100, hit_threshold=1,
                        ranking_cfg=RANKING, seed=42)
    assert ev.n_candidates == 3
    assert ev.n_hits == 2  # H1, H2
    for m in ev.methods.values():
        assert 0.0 <= m.precision_at[10] <= 1.0
        assert 0.0 <= m.recall_at[10] <= 1.0
