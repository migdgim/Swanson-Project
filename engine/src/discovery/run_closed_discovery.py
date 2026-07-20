"""Runner S1: costruisce il grafo A-B-C e verifica il gate dei B noti.

Uso:
    python -m discovery.run_closed_discovery     # da engine/src, con .venv attivo

Gate (DesignArchitecture.md §8): se ritrova < 5 dei 7 B noti, la pipeline e' rotta
-> stop & report. Non prosegue automaticamente a S2.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

try:
    from .closed_discovery import closed_discovery, known_b_gate
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from discovery.closed_discovery import closed_discovery, known_b_gate

from graph.build_graph import NODE_A, NODE_C, build_corridor_graph
from ingest.cache import Cache

_ENGINE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"

GATE_MIN = 5  # >= 5 dei 7 B noti, altrimenti stop


def main() -> int:
    parser = argparse.ArgumentParser(description="Closed discovery S1 + gate B noti.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--top", type=int, default=25, help="quanti B mostrare nel report")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    cache = Cache(args.db)
    try:
        graph = build_corridor_graph(cache, config)
        candidates = closed_discovery(graph, config["ranking"])
        hits, found = known_b_gate(candidates, config["known_b_terms"])
    finally:
        cache.close()

    n_b = graph.number_of_nodes() - 2
    print("=" * 64)
    print("CLOSED DISCOVERY — S1")
    print("=" * 64)
    print(f"  Paper nel grafo (A ∪ C): {graph.graph['total_papers']}")
    print(f"  A (df): {graph.nodes[NODE_A]['df']}  |  C (df): {graph.nodes[NODE_C]['df']}")
    print(f"  Nodi B candidati (dopo filtro df): {len(candidates)} su {n_b} descrittori totali")

    print(f"\n  Top {args.top} B per score di linking (a_df*c_df/total_df):")
    print(f"    {'rank':>4}  {'a_df':>5} {'c_df':>5} {'tot':>5} {'score':>7}  descrittore")
    for b in candidates[: args.top]:
        print(f"    {b.rank:>4}  {b.a_df:>5} {b.c_df:>5} {b.total_df:>5} {b.score:>7.2f}  {b.label}")

    print("\n  GATE — B noti ritrovati:")
    for h in hits:
        if h.rank is not None:
            print(f"    [OK]   {h.label:32s} -> '{h.matched_descriptor}' (rank {h.rank})")
        else:
            print(f"    [MISS] {h.label:32s} -> non tra i candidati")

    print("\n" + "=" * 64)
    verdict = "PASS" if found >= GATE_MIN else "FAIL"
    print(f"  B noti ritrovati: {found}/{len(hits)}  (soglia gate: >= {GATE_MIN})  => {verdict}")
    if verdict == "FAIL":
        print("  Gate NON superato: la pipeline non ritrova abbastanza B noti.")
        print("  STOP: non si prosegue a S2 senza risolvere (vedi DesignArchitecture.md §8).")
    print("=" * 64)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
