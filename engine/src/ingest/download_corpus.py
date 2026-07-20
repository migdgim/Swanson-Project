"""Runner S0: scarica e cachea il corpus pilota A<->C, poi stampa i conteggi.

Uso:
    python -m ingest.download_corpus            # dalla dir engine/src, con .venv attivo
    python engine/src/ingest/download_corpus.py # dalla project root

Legge i parametri da `engine/config/pilot.yaml` e i segreti da `.env` (mai hardcoded).
Idempotente: una seconda esecuzione non ri-scarica nulla (cache SQLite in engine/data/).
Non e' un gate automatico: stampa i numeri, il giudizio e' del committente.
"""

from __future__ import annotations

import argparse
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

# Import robusto sia come modulo (`-m ingest.download_corpus`) sia come script diretto.
try:
    from .cache import Cache
    from .entrez_client import EntrezClient
except ImportError:  # eseguito come file: aggiungi engine/src al path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingest.cache import Cache
    from ingest.entrez_client import EntrezClient

# Radici del progetto ricavate dalla posizione del file: engine/src/ingest/ -> ...
_INGEST_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _INGEST_DIR.parents[1]
_PROJECT_ROOT = _ENGINE_DIR.parent

CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
ENV_PATH = _PROJECT_ROOT / ".env"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _load_secrets() -> dict[str, str | None]:
    """Segreti da ambiente (impostato dal committente) con fallback su .env."""
    import os

    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return {
        "NCBI_API_KEY": os.environ.get("NCBI_API_KEY") or file_vals.get("NCBI_API_KEY"),
        "NCBI_EMAIL": os.environ.get("NCBI_EMAIL") or file_vals.get("NCBI_EMAIL"),
    }


def _fetch_corridor(
    client: EntrezClient, name: str, cfg: dict[str, Any], ingest_cfg: dict[str, Any]
) -> dict[str, Any]:
    query = cfg["mesh_query"]
    min_year = int(ingest_cfg["min_year"])
    max_year = int(ingest_cfg["max_year"])
    strategy = str(ingest_cfg.get("sampling", "per_year"))
    print(f"\n[{name}] {cfg['label']}")
    print(f"    query: {query}  | strategia: {strategy}")

    if strategy == "flat":
        retmax = int(ingest_cfg["retmax"])
        pmids, total = client.search_pmids(
            query, retmax=retmax, min_year=min_year, max_year=max_year
        )
        truncated = total > len(pmids)
        print(f"    hit su PubMed: {total} | recuperati (retmax={retmax}): {len(pmids)}"
              f"{'  [TRONCATO/recency-biased]' if truncated else ''}")
        return {"name": name, "pmids": pmids, "total_hits": total, "truncated": truncated}

    # per_year: un taglio per ciascun anno, cosi' le finestre DEV/TEST sono coperte.
    cap = int(ingest_cfg["per_year_cap"])
    collected: list[str] = []
    seen: set[str] = set()
    total_hits = 0
    capped_years = 0
    for year in range(min_year, max_year + 1):
        year_pmids, year_total = client.search_pmids(
            query, retmax=cap, min_year=year, max_year=year
        )
        total_hits += year_total
        if year_total > len(year_pmids):
            capped_years += 1
        for p in year_pmids:
            if p not in seen:
                seen.add(p)
                collected.append(p)
    print(f"    hit totali su PubMed ({min_year}-{max_year}): {total_hits} | "
          f"recuperati (cap {cap}/anno): {len(collected)} | anni saturati: {capped_years}")
    return {"name": name, "pmids": collected, "total_hits": total_hits,
            "truncated": capped_years > 0}


def _print_report(cache: Cache, corridors: list[dict[str, Any]], ts: dict[str, Any]) -> None:
    print("\n" + "=" * 64)
    print("REPORT CORPUS S0")
    print("=" * 64)

    for c in corridors:
        flag = "  [TRONCATO: la query rende piu' hit del retmax]" if c["truncated"] else ""
        print(f"  {c['name']}: hit={c['total_hits']}  recuperati={len(c['pmids'])}{flag}")

    union = set()
    for c in corridors:
        union.update(c["pmids"])
    overlap = len(corridors[0]["pmids"]) + len(corridors[1]["pmids"]) - len(union) if len(
        corridors
    ) == 2 else 0

    total_papers = cache.count_papers()
    with_abs = cache.count_with_abstract()
    print(f"\n  PMID unici richiesti (A ∪ C): {len(union)}")
    if len(corridors) == 2:
        print(f"  Sovrapposizione A ∩ C (co-occorrenza): {overlap}")
    print(f"  Paper in cache: {total_papers}")
    pct = (100.0 * with_abs / total_papers) if total_papers else 0.0
    print(f"  Con abstract non vuoto: {with_abs} ({pct:.1f}%)")

    # Sanity per il time-slicing (finestre da config).
    dev = ts["dev"]
    test = ts["test"]
    dev_max = int(str(dev["graph_max_date"])[:4])
    dev_hi = int(str(dev["eval_window"][1])[:4])
    dev_lo = int(str(dev["eval_window"][0])[:4])
    test_max = int(str(test["graph_max_date"])[:4])
    test_hi = int(str(test["eval_window"][1])[:4])
    test_lo = int(str(test["eval_window"][0])[:4])
    print("\n  Ripartizione per il time-slicing:")
    print(f"    DEV  grafo (<= {dev_max}):           {cache.count_papers_max_year(dev_max)}")
    print(f"    DEV  eval  ({dev_lo}-{dev_hi}):       {cache.count_papers_between(dev_lo, dev_hi)}")
    print(f"    TEST grafo (<= {test_max}):           {cache.count_papers_max_year(test_max)}")
    print(f"    TEST eval  ({test_lo}-{test_hi}):     {cache.count_papers_between(test_lo, test_hi)}")

    by_year = cache.counts_by_year()
    unknown = sum(n for y, n in by_year if y is None)
    print(f"\n  Paper senza anno estraibile: {unknown}")
    print("\n  Conteggio per anno:")
    for y, n in by_year:
        if y is None:
            continue
        bar = "#" * min(60, n // max(1, (total_papers // 200) or 1))
        print(f"    {y}: {n:5d} {bar}")
    print("=" * 64)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download del corpus pilota S0 (A<->C).")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    secrets = _load_secrets()
    api_key = secrets["NCBI_API_KEY"]
    email = secrets["NCBI_EMAIL"]
    if not api_key or not email:
        print("BLOCCO: NCBI_API_KEY e/o NCBI_EMAIL non impostati (env o .env).")
        print("        Prerequisito bloccante per l'ingest — vedi ActualStatus.md.")
        return 2

    corridor = config["corridor"]
    ingest_cfg = config["ingest"]

    cache = Cache(args.db)
    try:
        client = EntrezClient(
            api_key=api_key,
            email=email,
            cache=cache,
            rate_per_sec=int(ingest_cfg.get("api_rate_per_sec", 10)),
        )

        corridors = [
            _fetch_corridor(client, "A", corridor["A"], ingest_cfg),
            _fetch_corridor(client, "C", corridor["C"], ingest_cfg),
        ]

        union: list[str] = []
        seen: set[str] = set()
        for c in corridors:
            for p in c["pmids"]:
                if p not in seen:
                    seen.add(p)
                    union.append(p)

        print(f"\n[efetch] scarico {len(union)} PMID unici (i gia' in cache sono saltati)...")
        saved = client.fetch_papers(union)
        print(f"[efetch] nuovi paper salvati: {saved}")

        cache.record_run(
            run_id=str(uuid.uuid4()),
            git_sha=_git_sha(),
            config_snapshot=config,
            split="ingest",
            graph_max_date=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        _print_report(cache, corridors, config["time_slicing"])
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
