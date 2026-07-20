"""Estrazione relazioni grounded sul corpus (o sottoinsieme pre-cutoff), RIPRENDIBILE.

Ogni estrazione è cacheata su disco (`llm_extractions`): un run interrotto (limite
giornaliero free-tier, standby, Ctrl-C) riprende da dove era, senza rifare né ripagare.
Su quota esaurita (429) il runner si ferma pulito e riporta quanti restano.

Scope di default: paper dei corridoi A∪C con abstract e `pub_year <= max_year`
(il grafo predittivo del time-slicing S2 usa solo il pre-cutoff). `max_year` dal config
(`relations.extract_max_year`), sovrascrivibile da CLI.

Uso:
    python -m relations.extract_corpus                 # pre-cutoff (<=2021), riprendibile
    python -m relations.extract_corpus --max-year 2018 # solo grafo DEV
    python -m relations.extract_corpus --max-year 0    # 0 = nessun limite (tutto il corpus)
    python -m relations.extract_corpus --limit 200     # tetto per questa sessione (batch)

NON ricostruisce il grafo né esegue S2: è solo l'accumulo delle estrazioni.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values

try:
    from .gemini_source import GeminiRelationSource
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from relations.gemini_source import GeminiRelationSource

from ingest.cache import Cache

_ENGINE_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _ENGINE_DIR.parent
CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"
ENV_PATH = _PROJECT_ROOT / ".env"

# Eccezione di quota esaurita del client Google (import difensivo: non è tipizzato).
try:
    from google.api_core.exceptions import ResourceExhausted
except Exception:  # noqa: BLE001
    ResourceExhausted = None


def _secret(name: str) -> str | None:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return os.environ.get(name) or file_vals.get(name)


def _target_pmids(cache: Cache, max_year: int) -> list[tuple[str, str | None, str]]:
    """(pmid, title, abstract) dei paper A∪C con abstract, pub_year<=max_year (0 = tutti).
    Ordinato per pmid: deterministico e riprendibile."""
    if max_year and max_year > 0:
        rows = cache._conn.execute(  # noqa: SLF001 - lettura interna consentita nel motore
            "SELECT DISTINCT p.pmid, p.title, p.abstract FROM papers p "
            "JOIN paper_corridor pc ON pc.pmid = p.pmid "
            "WHERE p.abstract IS NOT NULL AND p.abstract != '' "
            "AND p.pub_year IS NOT NULL AND p.pub_year <= ? ORDER BY p.pmid",
            (max_year,),
        ).fetchall()
    else:
        rows = cache._conn.execute(  # noqa: SLF001
            "SELECT DISTINCT p.pmid, p.title, p.abstract FROM papers p "
            "JOIN paper_corridor pc ON pc.pmid = p.pmid "
            "WHERE p.abstract IS NOT NULL AND p.abstract != '' ORDER BY p.pmid",
        ).fetchall()
    return [(str(r["pmid"]), r["title"], str(r["abstract"])) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Estrazione relazioni grounded (riprendibile).")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--max-year", type=int, default=None, help="0 = nessun limite")
    parser.add_argument("--limit", type=int, default=None, help="tetto estrazioni per questo run")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    rc = config["relations"]

    api_key = _secret("GEMINI_API_KEY")
    if not api_key:
        print("BLOCCO: GEMINI_API_KEY non impostata (env o .env). Stop.")
        return 2

    model = _secret("GEMINI_MODEL") or str(rc["model"])
    max_year = args.max_year if args.max_year is not None else int(rc.get("extract_max_year", 2021))
    rpm = int(rc.get("client_rpm", rc["free_tier"]["rpm"]))

    cache = Cache(args.db)
    try:
        targets = _target_pmids(cache, max_year)
        total = len(targets)
        if total == 0:
            print("BLOCCO: nessun paper target. Esegui prima l'ingest. Stop.")
            return 2

        src = GeminiRelationSource(
            api_key=api_key,
            model=model,
            cache=cache,
            temperature=float(rc["temperature"]),
            max_output_tokens=int(rc["max_output_tokens"]),
            rate_per_min=rpm,
        )

        scope = f"pub_year<={max_year}" if max_year and max_year > 0 else "tutto il corpus"
        print("=" * 64)
        print("ESTRAZIONE RELAZIONI GROUNDED (riprendibile)")
        print("=" * 64)
        print(f"  Modello: {model} | temp={rc['temperature']} | prompt={rc['prompt_version']}")
        print(f"  Scope: {scope} -> {total} paper target (A∪C con abstract)")
        print(f"  Rate: {rpm} req/min | cache-first (skip già estratti)\n")

        done_fresh = 0
        done_cached = 0
        n_rel = 0
        n_err = 0
        budget = args.limit if args.limit is not None else total
        for i, (pmid, title, abstract) in enumerate(targets, start=1):
            if done_fresh >= budget:
                print(f"\n  Tetto --limit={budget} raggiunto per questo run. Riprendi per continuare.")
                break
            try:
                res = src.extract(pmid=pmid, title=title, abstract=abstract)
            except Exception as exc:  # noqa: BLE001
                if ResourceExhausted is not None and isinstance(exc, ResourceExhausted):
                    print(f"\n  QUOTA free-tier esaurita a {i-1}/{total}. "
                          f"Stop pulito: riprendi domani (le estrazioni fatte sono in cache).")
                    break
                n_err += 1
                print(f"  [{i:>4}/{total}] pmid={pmid:>9} ERRORE: "
                      f"{type(exc).__name__}: {str(exc).splitlines()[0][:70]}")
                continue
            n_rel += len(res.relations)
            if res.cached:
                done_cached += 1
            else:
                done_fresh += 1
                if done_fresh % 25 == 0:
                    print(f"  [{i:>4}/{total}] estratti freschi: {done_fresh} | rel finora: {n_rel}")

        extracted_total = cache.count_llm_extractions(model=model)
        print("\n" + "-" * 64)
        print(f"  Estrazioni fresche in questo run: {done_fresh}")
        print(f"  Già in cache (saltate): {done_cached} | errori non-quota: {n_err}")
        print(f"  Relazioni viste in questo run: {n_rel}")
        print(f"  TOTALE estrazioni in cache per {model}: {extracted_total}/{total}")
        remaining = total - extracted_total
        if remaining > 0:
            print(f"  Restano ~{remaining} paper: ri-esegui lo stesso comando per continuare.")
        else:
            print("  Copertura completa dello scope. Pronto per la ricostruzione del grafo (prossimo step).")
        print("=" * 64)
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
