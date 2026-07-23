"""Runner OPEN DISCOVERY time-sliced: il verdetto anti-tautologia.

Il task closed (`run_time_slicing.py`) premia la frequenza per costruzione (un B già
ponte resta ponte). Qui il candidato è un B collegato a UN SOLO corridoio pre-cutoff e
l'hit è l'*acquisizione* del lato mancante post-cutoff (il ponte A-B-C si chiude).

Domanda pre-registrata (prima di vedere i numeri): l'evidenza relazionale grounded del
lato presente predice la chiusura del ponte meglio della sola frequenza di co-occorrenza?
Verdetto: grounded P@k0 > frequenza P@k0 (e >= random). Protocollo: taratura di N SOLO su
DEV con regola neutra fissata a priori, poi TEST una volta sola a N congelato.

Uso:
    python -m validation.run_open_discovery     # da engine/src, con .venv attivo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

try:
    from .time_slicing import SplitEvaluation, evaluate_open_split
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validation.time_slicing import SplitEvaluation, evaluate_open_split

from graph.build_graph import NODE_A, NODE_C, build_corridor_graph
from ingest.cache import Cache

_ENGINE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"

N_SWEEP = [1, 2, 3, 5]
_METHOD_ORDER = ("grounded", "frequency", "random")


def _year(s: str) -> int:
    return int(str(s)[:4])


def _pre_sizes(cache: Cache, cutoff: int) -> tuple[int, int]:
    return cache.count_corridor_max_year("A", cutoff), cache.count_corridor_max_year("C", cutoff)


def _grounded_years(
    cache: Cache, config: dict[str, Any]
) -> dict[str, tuple[list[int], list[int]]]:
    """Per ogni B: (anni-paper con relazione LLM sul lato A, idem lato C). Da usare come
    segnale, non come filtro dei candidati."""
    model = str(config["relations"]["model"])
    extractions = cache.iter_llm_extractions(model)
    if not extractions:
        raise SystemExit(
            f"BLOCCO: nessuna estrazione LLM in cache per {model}. "
            f"Esegui prima 'python -m relations.extract_corpus'. Stop."
        )
    relations_by_pmid: dict[str, list[dict[str, Any]]] = {}
    for pmid, resp_json in extractions:
        payload = json.loads(resp_json)
        rels = payload.get("relations", []) if isinstance(payload, dict) else []
        relations_by_pmid[pmid] = rels
    # Matching PLAIN, UNIFORME su tutti i descrittori (sinonimi solo-per-B-noti = p-hacking).
    g_gr = build_corridor_graph(cache, config, relations_by_pmid=relations_by_pmid)
    out: dict[str, tuple[list[int], list[int]]] = {}
    for node, data in g_gr.nodes(data=True):
        if data.get("kind") != "mesh":
            continue
        a_years = g_gr[NODE_A][node]["years"] if g_gr.has_edge(NODE_A, node) else []
        c_years = g_gr[node][NODE_C]["years"] if g_gr.has_edge(node, NODE_C) else []
        out[str(node)] = (a_years, c_years)
    return out


def _print_methods(ev: SplitEvaluation, ks: list[int]) -> None:
    print(f"    candidati (mezzo-ponte): {ev.n_candidates} | hit (N={ev.hit_threshold}): "
          f"{ev.n_hits}")
    header = "    " + f"{'metodo':>10}  " + "  ".join(f"P@{k:<3}" for k in ks) + "   " + \
             "  ".join(f"R@{k:<3}" for k in ks)
    print(header)
    for name in _METHOD_ORDER:
        m = ev.methods.get(name)
        if m is None:
            continue
        p = "  ".join(f"{m.precision_at[k]:.3f}" for k in ks)
        r = "  ".join(f"{m.recall_at[k]:.3f}" for k in ks)
        print(f"    {name:>10}  {p}   {r}")


def _select_threshold(cache: Cache, graph: Any, dev: dict[str, Any], ranking: dict[str, Any],
                      seed: int, ks: list[int],
                      grounded_years: dict[str, tuple[list[int], list[int]]]) -> int:
    """Regola neutra fissata a priori: il piu' piccolo N con >=10 hit e hit-rate <=0.5.
    Non guarda le performance dei metodi -> niente p-hacking."""
    cutoff = _year(dev["graph_max_date"])
    lo, hi = _year(dev["eval_window"][0]), _year(dev["eval_window"][1])
    n_pre_a, n_pre_c = _pre_sizes(cache, cutoff)
    print(f"\n[DEV] cutoff={cutoff} eval={lo}-{hi} | corridoi pre-cutoff A={n_pre_a} C={n_pre_c}")
    chosen: int | None = None
    for n in N_SWEEP:
        ev = evaluate_open_split(graph, "dev", cutoff, (lo, hi), n_pre_a, n_pre_c, n, ranking,
                                 seed, grounded_years)
        rate = ev.n_hits / ev.n_candidates if ev.n_candidates else 0.0
        mark = ""
        if chosen is None and ev.n_hits >= 10 and rate <= 0.5:
            chosen = n
            mark = "  <- scelto (regola: >=10 hit, hit-rate<=0.5)"
        print(f"  N={n}: candidati={ev.n_candidates} hit={ev.n_hits} hit-rate={rate:.2f}{mark}")
        if n == chosen:
            _print_methods(ev, ks)
    return chosen if chosen is not None else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Open discovery time-sliced (DEV tune, TEST once).")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    ranking = config["ranking"]
    ks = [int(k) for k in ranking["top_k"]]
    seed = int(config.get("seed", 42))
    ts = config["time_slicing"]

    cache = Cache(args.db)
    try:
        graph = build_corridor_graph(cache, config)  # candidati + ground-truth (osservabile)
        grounded_years = _grounded_years(cache, config)
        print("=" * 68)
        print("OPEN DISCOVERY (time-sliced) — chiusura del ponte A-B-C")
        print("=" * 68)
        print(f"  Paper nel grafo (A ∪ C): {graph.graph['total_papers']}")

        # 1) Taratura N su DEV.
        n_star = _select_threshold(cache, graph, ts["dev"], ranking, seed, ks, grounded_years)
        print(f"\n  >> Soglia-hit congelata su DEV: N = {n_star}")

        # 2) TEST una volta sola.
        test = ts["test"]
        cutoff = _year(test["graph_max_date"])
        lo, hi = _year(test["eval_window"][0]), _year(test["eval_window"][1])
        n_pre_a, n_pre_c = _pre_sizes(cache, cutoff)
        print(f"\n[TEST] (una sola esecuzione) cutoff={cutoff} eval={lo}-{hi} | "
              f"corridoi pre-cutoff A={n_pre_a} C={n_pre_c}")
        ev = evaluate_open_split(graph, "test", cutoff, (lo, hi), n_pre_a, n_pre_c,
                                 n_star, ranking, seed, grounded_years)
        _print_methods(ev, ks)

        print("\n  Top-10 candidati del modello (grounded) NON confermati su TEST:")
        for fp in ev.methods["grounded"].top_false_positives:
            print(f"    - {fp}")

        # 3) Verdetto pre-registrato: grounded batte la frequenza?
        k0 = ks[0]
        g_p = ev.methods["grounded"].precision_at[k0]
        freq_p = ev.methods["frequency"].precision_at[k0]
        rnd_p = ev.methods["random"].precision_at[k0]
        print("\n" + "=" * 68)
        print(f"  VERDETTO (P@{k0}):  grounded={g_p:.3f}  frequenza={freq_p:.3f}  "
              f"random={rnd_p:.3f}")
        if g_p > freq_p and g_p >= rnd_p:
            print("  => PASS: l'evidenza grounded predice la chiusura del ponte meglio della")
            print("     sola frequenza. Il layer relazionale aggiunge valore.")
            verdict = 0
        else:
            print("  => FAIL: il grounded NON batte la frequenza sulla chiusura del ponte.")
            print("     Onestamente: su questo corpus il segnale relazionale non aggiunge")
            print("     potere predittivo oltre la frequenza. Vedi note nel report.")
            verdict = 1
        print("=" * 68)
    finally:
        cache.close()
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
