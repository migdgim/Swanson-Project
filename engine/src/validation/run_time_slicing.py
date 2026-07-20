"""Runner S2: time-slicing DEV/TEST -> verdetto pass/fail sul potere predittivo.

Uso:
    python -m validation.run_time_slicing     # da engine/src, con .venv attivo

Protocollo (anti-contaminazione):
  1. Taratura della soglia-hit N SOLO su DEV, con regola neutra fissata a priori
     (non per favorire il modello).
  2. Esecuzione UNA VOLTA su TEST a N congelato.
Verdetto: il modello (PMI) deve battere il baseline a frequenza, altrimenti il
sistema e' dichiarato non funzionante (DesignArchitecture.md §9).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

try:
    from .time_slicing import SplitEvaluation, evaluate_split
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validation.time_slicing import SplitEvaluation, evaluate_split

from graph.build_graph import build_corridor_graph
from ingest.cache import Cache

_ENGINE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"

N_SWEEP = [1, 2, 3, 5]


def _year(s: str) -> int:
    return int(str(s)[:4])


def _pre_sizes(cache: Cache, cutoff: int) -> tuple[int, int]:
    return cache.count_corridor_max_year("A", cutoff), cache.count_corridor_max_year("C", cutoff)


def _print_methods(ev: SplitEvaluation, ks: list[int]) -> None:
    print(f"    candidati B: {ev.n_candidates} | hit (N={ev.hit_threshold}): {ev.n_hits}")
    header = "    " + f"{'metodo':>10}  " + "  ".join(f"P@{k:<3}" for k in ks) + "   " + \
             "  ".join(f"R@{k:<3}" for k in ks)
    print(header)
    for name in ("pmi", "frequency", "random"):
        m = ev.methods[name]
        p = "  ".join(f"{m.precision_at[k]:.3f}" for k in ks)
        r = "  ".join(f"{m.recall_at[k]:.3f}" for k in ks)
        print(f"    {name:>10}  {p}   {r}")


def _select_threshold(cache: Cache, graph: Any, dev: dict[str, Any], ranking: dict[str, Any],
                      seed: int, ks: list[int]) -> int:
    """Regola neutra fissata a priori: il piu' piccolo N con >=10 hit e hit-rate <=0.5.
    Non guarda le performance dei metodi -> niente p-hacking."""
    cutoff = _year(dev["graph_max_date"])
    lo, hi = _year(dev["eval_window"][0]), _year(dev["eval_window"][1])
    n_pre_a, n_pre_c = _pre_sizes(cache, cutoff)
    print(f"\n[DEV] cutoff={cutoff} eval={lo}-{hi} | corridoi pre-cutoff A={n_pre_a} C={n_pre_c}")
    chosen: int | None = None
    for n in N_SWEEP:
        ev = evaluate_split(graph, "dev", cutoff, (lo, hi), n_pre_a, n_pre_c, n, ranking, seed)
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
    parser = argparse.ArgumentParser(description="Time-slicing S2 (DEV tune, TEST once).")
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
        graph = build_corridor_graph(cache, config)
        print("=" * 68)
        print("TIME-SLICING — S2")
        print("=" * 68)
        print(f"  Paper nel grafo (A ∪ C): {graph.graph['total_papers']}")

        # 1) Taratura N su DEV.
        n_star = _select_threshold(cache, graph, ts["dev"], ranking, seed, ks)
        print(f"\n  >> Soglia-hit congelata su DEV: N = {n_star}")

        # 2) TEST una volta sola.
        test = ts["test"]
        cutoff = _year(test["graph_max_date"])
        lo, hi = _year(test["eval_window"][0]), _year(test["eval_window"][1])
        n_pre_a, n_pre_c = _pre_sizes(cache, cutoff)
        print(f"\n[TEST] (una sola esecuzione) cutoff={cutoff} eval={lo}-{hi} | "
              f"corridoi pre-cutoff A={n_pre_a} C={n_pre_c}")
        ev = evaluate_split(graph, "test", cutoff, (lo, hi), n_pre_a, n_pre_c,
                            n_star, ranking, seed)
        _print_methods(ev, ks)

        print("\n  Top-10 falsi positivi del modello (PMI) su TEST:")
        for fp in ev.methods["pmi"].top_false_positives:
            print(f"    - {fp}")

        # 3) Verdetto: PMI batte la frequenza?
        k0 = ks[0]
        pmi_p = ev.methods["pmi"].precision_at[k0]
        freq_p = ev.methods["frequency"].precision_at[k0]
        rnd_p = ev.methods["random"].precision_at[k0]
        print("\n" + "=" * 68)
        print(f"  VERDETTO (P@{k0}):  PMI={pmi_p:.3f}  frequenza={freq_p:.3f}  random={rnd_p:.3f}")
        if pmi_p > freq_p and pmi_p >= rnd_p:
            print("  => PASS: il modello (PMI) batte il baseline a frequenza.")
            verdict = 0
        else:
            print("  => FAIL: il modello NON batte il baseline a frequenza.")
            print("     Onestamente: su questo corpus/segnale il sistema non aggiunge valore")
            print("     oltre la frequenza pura. Vedi note nel report per le cause probabili.")
            verdict = 1
        print("=" * 68)
    finally:
        cache.close()
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
