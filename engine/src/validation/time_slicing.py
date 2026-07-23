"""Time-slicing (S2): il verdetto binario sul potere predittivo.

Contratto (DesignArchitecture.md §9):
- Maschera temporale: si guarda al grafo com'era a `graph_max_date` (cutoff) e si
  predice quali B collegheranno A e C; poi si verifica nella finestra post-cutoff.
- Ground truth (hit): un B e' un "hit" se nella finestra di valutazione ha >= N
  papers A-B *e* >= N papers B-C (il ponte A-B-C si materializza/regge). N tarato su DEV.
- Baseline: frequenza pura + random. Il modello deve batterli o e' dichiarato non funzionante.
- Separazione DEV/TEST: il TEST si esegue UNA VOLTA, a parametri congelati su DEV.

La maschera e' una semplice lettura degli anni sugli archi del grafo gia' costruito:
non si ricostruisce nulla (gli archi portano `years`, ordinati).
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import networkx as nx

from graph.build_graph import NODE_A, NODE_C


class _Labeled(Protocol):
    label: str


def _years(graph: nx.Graph, b: str, side: str) -> list[int]:
    if side == "A" and graph.has_edge(NODE_A, b):
        years: list[int] = graph[NODE_A][b]["years"]
        return years
    if side == "C" and graph.has_edge(b, NODE_C):
        years2: list[int] = graph[b][NODE_C]["years"]
        return years2
    return []


def _le(sorted_years: list[int], cutoff: int) -> int:
    return bisect.bisect_right(sorted_years, cutoff)


def _between(sorted_years: list[int], lo: int, hi: int) -> int:
    return bisect.bisect_right(sorted_years, hi) - bisect.bisect_left(sorted_years, lo)


@dataclass
class BSlice:
    label: str
    a_pre: int
    c_pre: int
    a_post: int
    c_post: int
    freq_score: float = 0.0       # baseline: frequenza pura pre-cutoff (co-occorrenza)
    pmi_score: float = 0.0         # PMI(B;A)+PMI(B;C) pre-cutoff sulla co-occorrenza
    grounded_score: float = 0.0    # modello LLM: PMI sui SOLI paper con relazione grounded

    def is_hit(self, n: int) -> bool:
        return self.a_post >= n and self.c_post >= n


@dataclass
class MethodResult:
    name: str
    precision_at: dict[int, float] = field(default_factory=dict)
    recall_at: dict[int, float] = field(default_factory=dict)
    top_false_positives: list[str] = field(default_factory=list)


@dataclass
class SplitEvaluation:
    split: str
    cutoff: int
    window: tuple[int, int]
    n_candidates: int
    n_hits: int
    hit_threshold: int
    methods: dict[str, MethodResult]


def build_slices(
    graph: nx.Graph,
    cutoff: int,
    window: tuple[int, int],
    n_pre_a: int,
    n_pre_c: int,
    ranking_cfg: dict[str, Any],
    grounded_years: dict[str, tuple[list[int], list[int]]] | None = None,
) -> list[BSlice]:
    """Candidati B che collegano A e C nel grafo pre-cutoff, con score frequenza e PMI.
    Filtro df (df_min/df_max_ratio) sul pre-cutoff, uguale per tutti i ranking (fair).

    Candidati e ground-truth vengono SEMPRE dalla co-occorrenza (fenomeno osservabile,
    non decimato). Se `grounded_years` è fornito, ogni candidato riceve in più un
    `grounded_score` = PMI calcolato sui soli anni-paper in cui B è relazionalmente
    supportato (archi del grafo grounded). Il grounding diventa così un *segnale di
    ranking* sullo stesso insieme di candidati, non un filtro che svuota il grafo."""
    lo, hi = window
    df_min = int(ranking_cfg["df_min"])
    df_max_ratio = float(ranking_cfg["df_max_ratio"])
    n_pre_total = n_pre_a + n_pre_c
    df_max = df_max_ratio * n_pre_total

    slices: list[BSlice] = []
    for node, data in graph.nodes(data=True):
        if data.get("kind") != "mesh":
            continue
        a_years = _years(graph, node, "A")
        c_years = _years(graph, node, "C")
        a_pre = _le(a_years, cutoff)
        c_pre = _le(c_years, cutoff)
        if a_pre < 1 or c_pre < 1:
            continue  # non collega A e C nel grafo pre-cutoff
        total_pre = a_pre + c_pre  # proxy (overlap A∩C trascurabile, <=12 paper)
        if total_pre < df_min or total_pre > df_max:
            continue
        a_post = _between(a_years, lo, hi)
        c_post = _between(c_years, lo, hi)

        s = BSlice(str(node), a_pre, c_pre, a_post, c_post)
        s.freq_score = float(a_pre + c_pre)
        s.pmi_score = _pmi(a_pre, c_pre, n_pre_a, n_pre_c)
        if grounded_years is not None:
            g_a_years, g_c_years = grounded_years.get(str(node), ([], []))
            g_a_pre = _le(g_a_years, cutoff)
            g_c_pre = _le(g_c_years, cutoff)
            s.grounded_score = _pmi(g_a_pre, g_c_pre, n_pre_a, n_pre_c)
        slices.append(s)
    return slices


def _pmi(a_pre: int, c_pre: int, n_pre_a: int, n_pre_c: int) -> float:
    """PMI(B;A) + PMI(B;C): specificita' rispetto al tasso base. Demota i termini ubiqui.

    p(B|A)=a_pre/N_A, tasso base p(B)=(a_pre+c_pre)/(N_A+N_C). PMI = log(p(B|corr)/p(B))."""
    if n_pre_a == 0 or n_pre_c == 0:
        return 0.0
    p_base = (a_pre + c_pre) / (n_pre_a + n_pre_c)
    if p_base == 0:
        return 0.0
    p_a = a_pre / n_pre_a
    p_c = c_pre / n_pre_c
    pmi_a = math.log(p_a / p_base) if p_a > 0 else 0.0
    pmi_c = math.log(p_c / p_base) if p_c > 0 else 0.0
    return pmi_a + pmi_c


def _precision_recall(
    ranked: Sequence[_Labeled], hit_labels: set[str], ks: list[int]
) -> tuple[dict[int, float], dict[int, float]]:
    total_hits = len(hit_labels)
    prec: dict[int, float] = {}
    rec: dict[int, float] = {}
    for k in ks:
        topk = ranked[:k]
        tp = sum(1 for b in topk if b.label in hit_labels)
        prec[k] = tp / k if k else 0.0
        rec[k] = tp / total_hits if total_hits else 0.0
    return prec, rec


def evaluate_split(
    graph: nx.Graph,
    split: str,
    cutoff: int,
    window: tuple[int, int],
    n_pre_a: int,
    n_pre_c: int,
    hit_threshold: int,
    ranking_cfg: dict[str, Any],
    seed: int,
    grounded_years: dict[str, tuple[list[int], list[int]]] | None = None,
) -> SplitEvaluation:
    slices = build_slices(graph, cutoff, window, n_pre_a, n_pre_c, ranking_cfg, grounded_years)
    hit_labels = {s.label for s in slices if s.is_hit(hit_threshold)}
    ks = [int(k) for k in ranking_cfg["top_k"]]

    methods: dict[str, MethodResult] = {}

    def _mk(name: str, ranked: list[BSlice]) -> MethodResult:
        prec, rec = _precision_recall(ranked, hit_labels, ks)
        fps = [b.label for b in ranked[:10] if b.label not in hit_labels]
        return MethodResult(name, prec, rec, fps)

    # 'grounded' è il modello LLM (presente solo se sono passate le evidenze grounded).
    if grounded_years is not None:
        methods["grounded"] = _mk(
            "grounded", sorted(slices, key=lambda b: (-b.grounded_score, b.label))
        )
    methods["pmi"] = _mk("pmi", sorted(slices, key=lambda b: (-b.pmi_score, b.label)))
    methods["frequency"] = _mk(
        "frequency", sorted(slices, key=lambda b: (-b.freq_score, b.label))
    )
    rng = random.Random(seed)
    shuffled = slices[:]
    rng.shuffle(shuffled)
    methods["random"] = _mk("random", shuffled)

    return SplitEvaluation(
        split=split,
        cutoff=cutoff,
        window=window,
        n_candidates=len(slices),
        n_hits=len(hit_labels),
        hit_threshold=hit_threshold,
        methods=methods,
    )


# ---------------------------------------------------------------------------
# OPEN DISCOVERY (validazione anti-tautologia).
#
# Il task closed premia la frequenza per costruzione: un B già ponte A-B-C resta
# ponte (persistenza). Qui invece un candidato è un B collegato a UN SOLO corridoio
# pre-cutoff ("mezzo ponte"), e l'hit è l'*acquisizione* del lato mancante post-cutoff
# (il ponte si CHIUDE). Predire questa chiusura NON è tautologico con la frequenza:
# la domanda scientifica è se l'evidenza relazionale grounded del lato presente predice
# la chiusura meglio della sola frequenza di co-occorrenza.
# ---------------------------------------------------------------------------


@dataclass
class OpenSlice:
    label: str
    present: str            # "A" o "C": il corridoio a cui B è collegato pre-cutoff
    present_pre: int        # co-occorrenze pre-cutoff sul lato presente
    absent_post: int        # link acquisiti sul lato mancante nella finestra post-cutoff
    freq_score: float = 0.0        # baseline: frequenza del lato presente
    grounded_score: float = 0.0    # modello: co-occorrenze grounded del lato presente

    def is_hit(self, n: int) -> bool:
        return self.absent_post >= n


def build_open_slices(
    graph: nx.Graph,
    cutoff: int,
    window: tuple[int, int],
    n_pre_a: int,
    n_pre_c: int,
    ranking_cfg: dict[str, Any],
    grounded_years: dict[str, tuple[list[int], list[int]]] | None,
) -> list[OpenSlice]:
    """Candidati 'mezzo ponte' (collegati a un solo corridoio pre-cutoff) con score
    frequenza e grounded del lato presente. Filtro df sul lato presente (uguale per tutti)."""
    lo, hi = window
    df_min = int(ranking_cfg["df_min"])
    df_max = float(ranking_cfg["df_max_ratio"]) * (n_pre_a + n_pre_c)

    slices: list[OpenSlice] = []
    for node, data in graph.nodes(data=True):
        if data.get("kind") != "mesh":
            continue
        a_years = _years(graph, node, "A")
        c_years = _years(graph, node, "C")
        a_pre = _le(a_years, cutoff)
        c_pre = _le(c_years, cutoff)
        # Esattamente un lato collegato pre-cutoff (XOR): né 0 né 2.
        if (a_pre >= 1) == (c_pre >= 1):
            continue
        g_a, g_c = (grounded_years or {}).get(str(node), ([], []))
        if a_pre >= 1:
            present, present_pre = "A", a_pre
            absent_post = _between(c_years, lo, hi)
            grounded_pre = _le(g_a, cutoff)
        else:
            present, present_pre = "C", c_pre
            absent_post = _between(a_years, lo, hi)
            grounded_pre = _le(g_c, cutoff)
        if present_pre < df_min or present_pre > df_max:
            continue
        s = OpenSlice(str(node), present, present_pre, absent_post)
        s.freq_score = float(present_pre)
        s.grounded_score = float(grounded_pre)
        slices.append(s)
    return slices


def evaluate_open_split(
    graph: nx.Graph,
    split: str,
    cutoff: int,
    window: tuple[int, int],
    n_pre_a: int,
    n_pre_c: int,
    hit_threshold: int,
    ranking_cfg: dict[str, Any],
    seed: int,
    grounded_years: dict[str, tuple[list[int], list[int]]] | None,
) -> SplitEvaluation:
    slices = build_open_slices(graph, cutoff, window, n_pre_a, n_pre_c, ranking_cfg, grounded_years)
    hit_labels = {s.label for s in slices if s.is_hit(hit_threshold)}
    ks = [int(k) for k in ranking_cfg["top_k"]]

    def _mk(name: str, ranked: list[OpenSlice]) -> MethodResult:
        prec, rec = _precision_recall(ranked, hit_labels, ks)
        fps = [b.label for b in ranked[:10] if b.label not in hit_labels]
        return MethodResult(name, prec, rec, fps)

    methods: dict[str, MethodResult] = {}
    methods["grounded"] = _mk(
        "grounded", sorted(slices, key=lambda b: (-b.grounded_score, b.label))
    )
    methods["frequency"] = _mk(
        "frequency", sorted(slices, key=lambda b: (-b.freq_score, b.label))
    )
    rng = random.Random(seed)
    shuffled = slices[:]
    rng.shuffle(shuffled)
    methods["random"] = _mk("random", shuffled)

    return SplitEvaluation(
        split=split,
        cutoff=cutoff,
        window=window,
        n_candidates=len(slices),
        n_hits=len(hit_labels),
        hit_threshold=hit_threshold,
        methods=methods,
    )
