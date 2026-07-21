"""Copertura della normalizzazione menzione→MeSH sulle estrazioni già in cache.

Domanda (de-risking del prossimo sprint): quando l'LLM estrae relazioni da un abstract,
quanti descrittori MeSH di quel paper risultano *relazionalmente supportati* (menzionati
in una tripla)? E soprattutto: i **B noti** (IL-6, TNF-α, Treg, butirrato, LPS) vengono
agganciati? Confronta la copertura **senza** e **con** i sinonimi MeSH (entry-terms),
per quantificare quanto i sinonimi chiudono il gap abbreviazioni.

Uso:
    python -m relations.coverage_report        # da engine/src, con .venv attivo

NON costruisce grafi né esegue S2: solo misura. Funziona su qualunque copertura parziale.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values

try:
    from .normalize import supported_descriptors
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from relations.normalize import supported_descriptors

from graph.mesh import descriptors
from ingest.cache import Cache
from relations.mesh_synonyms import MeshSynonymSource

_ENGINE_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _ENGINE_DIR.parent
CONFIG_PATH = _ENGINE_DIR / "config" / "pilot.yaml"
DB_PATH = _ENGINE_DIR / "data" / "cache.sqlite"
ENV_PATH = _PROJECT_ROOT / ".env"


def _secret(name: str) -> str | None:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return os.environ.get(name) or file_vals.get(name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copertura normalizzazione menzione->MeSH.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    model = str(config["relations"]["model"])
    anchors: set[str] = set(config["corridor"]["A"].get("mesh_anchors", [])) | set(
        config["corridor"]["C"].get("mesh_anchors", [])
    )
    known_hints: list[str] = []
    for term in config["known_b_terms"]:
        known_hints += [d.strip() for d in str(term.get("hint", "")).split(";") if d.strip()]

    cache = Cache(args.db)
    try:
        extractions = cache.iter_llm_extractions(model)
        if not extractions:
            print(f"BLOCCO: nessuna estrazione in cache per {model}. Esegui l'estrazione. Stop.")
            return 2

        # Sinonimi SOLO per i descrittori dei B noti (bounded: ~9 descrittori, cacheati).
        syn_map: dict[str, list[str]] = {}
        api_key, email = _secret("NCBI_API_KEY"), _secret("NCBI_EMAIL")
        if api_key and email:
            src = MeshSynonymSource(api_key=api_key, email=email, cache=cache)
            for h in known_hints:
                try:
                    syn_map[h] = src.synonyms_for(h)
                except Exception as exc:  # noqa: BLE001 - onesto: rete assente => niente sinonimi
                    print(f"  [warn] sinonimi MeSH per '{h}' non recuperati: {type(exc).__name__}")
        else:
            print("  [warn] NCBI_API_KEY/EMAIL assenti: sezione 'con sinonimi' saltata.")

        def syn_of(d: str) -> list[str]:
            return syn_map.get(d, [d])

        n_papers = 0
        n_desc_total = 0
        n_desc_supported = 0
        papers_with_support = 0
        known_seen: dict[str, int] = {h: 0 for h in known_hints}
        known_sup_plain: dict[str, int] = {h: 0 for h in known_hints}
        known_sup_syn: dict[str, int] = {h: 0 for h in known_hints}

        for pmid, resp_json in extractions:
            raw = cache.get_raw_article(pmid)
            if raw is None:
                continue
            desc = {d for d in descriptors(json.loads(raw)) if d not in anchors}
            if not desc:
                continue
            payload = json.loads(resp_json)
            relations = payload.get("relations", []) if isinstance(payload, dict) else []
            supported = supported_descriptors(desc, relations)
            supported_syn = supported_descriptors(desc, relations, synonyms_of=syn_of)

            n_papers += 1
            n_desc_total += len(desc)
            n_desc_supported += len(supported)
            if supported:
                papers_with_support += 1
            for h in known_hints:
                if h in desc:
                    known_seen[h] += 1
                    if h in supported:
                        known_sup_plain[h] += 1
                    if h in supported_syn:
                        known_sup_syn[h] += 1

        print("=" * 68)
        print("COPERTURA NORMALIZZAZIONE menzione->MeSH")
        print("=" * 68)
        print(f"  Modello: {model} | paper estratti analizzati: {n_papers}")
        rate = n_desc_supported / n_desc_total if n_desc_total else 0.0
        print(f"  Descrittori MeSH (non-ancora) totali: {n_desc_total} | supportati (senza "
              f"sinonimi): {n_desc_supported} ({rate:.1%})")
        print("  (NB: il totale è gonfiato dai check-tag amministrativi, es. Humans/Adult/Male,")
        print("   che giustamente non compaiono mai in una relazione: guarda i B noti sotto.)")

        print("\n  Copertura sui descrittori dei B NOTI  —  senza sinonimi  ->  con sinonimi:")
        print(f"    {'descrittore':32s} {'visti':>6} {'senza':>8} {'con':>8}")
        for h in known_hints:
            seen = known_seen[h]
            if seen == 0:
                print(f"    {h[:32]:32s} {'0':>6} {'-':>8} {'-':>8}  (non nel campione)")
                continue
            p = f"{known_sup_plain[h]}/{seen}"
            s = f"{known_sup_syn[h]}/{seen}"
            n_syn = len(syn_map.get(h, []))
            print(f"    {h[:32]:32s} {seen:>6} {p:>8} {s:>8}  ({n_syn} forme MeSH)")

        print("\n" + "-" * 68)
        print("  Campione = pmid più bassi (paper più vecchi), NON rappresentativo del corpus.")
        print("  Serve a validare l'approccio, non a dare numeri finali.")
        print("=" * 68)
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
