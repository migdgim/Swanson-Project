"""Stima costo/fattibilità dell'estrazione relazioni LLM su un campione (S3-prep).

Compito (HANDOFF §Prossimo obiettivo, punto 4): PRIMA di estendere al corpus intero,
misurare su `sample_size` abstract i token reali e riportare:
  - token misurati (input/output) per abstract e totali;
  - estrapolazione al corpus (paper con abstract);
  - costo a listino (config, DA VERIFICARE) e fattibilità entro il free-tier (limiti in config).

Poi FERMARSI. Nessuna scrittura sul grafo, nessuna estensione automatica.

Uso:
    python -m relations.estimate_cost            # da engine/src, con .venv attivo
    python -m relations.estimate_cost --n 3      # smoke test veloce
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


def _secret(name: str) -> str | None:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return os.environ.get(name) or file_vals.get(name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stima costo/fattibilità estrazione LLM.")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--n", type=int, default=None, help="override sample_size del config")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    rc = config["relations"]

    api_key = _secret("GEMINI_API_KEY")
    if not api_key:
        print("BLOCCO: GEMINI_API_KEY non impostata (env o .env). Stop.")
        return 2

    model = _secret("GEMINI_MODEL") or str(rc["model"])
    n = int(args.n) if args.n is not None else int(rc["sample_size"])
    rpm = int(rc.get("client_rpm", rc["free_tier"]["rpm"]))

    cache = Cache(args.db)
    try:
        with_abstract = cache.count_with_abstract()
        sample = cache.sample_abstracts(limit=n)
        n = len(sample)
        if n == 0:
            print("BLOCCO: nessun abstract in cache. Esegui prima l'ingest. Stop.")
            return 2

        src = GeminiRelationSource(
            api_key=api_key,
            model=model,
            cache=cache,
            temperature=float(rc["temperature"]),
            max_output_tokens=int(rc["max_output_tokens"]),
            rate_per_min=rpm,
        )

        print("=" * 64)
        print("STIMA COSTO/FATTIBILITÀ — estrazione relazioni LLM (S3-prep)")
        print("=" * 64)
        print(f"  Modello: {model}  | temp={rc['temperature']} | prompt={rc['prompt_version']}")
        print(f"  Campione: {n} abstract (di {with_abstract} con abstract in cache)")
        print(f"  Rate limiting client: {rpm} req/min\n")

        tot_in = tot_out = tot_tok = 0
        n_rel = 0
        with_rel = 0
        parse_fail = 0
        n_cached = 0
        n_err = 0
        n_done = 0
        for i, (pmid, title, abstract) in enumerate(sample, start=1):
            try:
                res = src.extract(pmid=pmid, title=title, abstract=abstract)
            except Exception as exc:  # noqa: BLE001 - onesto: registriamo l'errore e proseguiamo
                n_err += 1
                print(f"    [{i:>3}/{n}] pmid={pmid:>9}  ERRORE: "
                      f"{type(exc).__name__}: {str(exc).splitlines()[0][:80]}")
                continue
            n_done += 1
            tot_in += res.usage.prompt_tokens
            tot_out += res.usage.output_tokens
            tot_tok += res.usage.total_tokens
            n_rel += len(res.relations)
            with_rel += 1 if res.relations else 0
            if not res.parse_ok:
                parse_fail += 1
            if res.cached:
                n_cached += 1
            flag = " (cache)" if res.cached else ""
            print(f"    [{i:>3}/{n}] pmid={pmid:>9}  rel={len(res.relations):>2}  "
                  f"tok in/out={res.usage.prompt_tokens}/{res.usage.output_tokens}{flag}")

        if n_done == 0:
            print("\nBLOCCO: nessuna estrazione riuscita (tutte in errore). "
                  "Verifica modello/quota. Stop.")
            return 3
        # Le medie usano n_done (estrazioni riuscite), non n (campione richiesto).
        n = n_done

        # I token da cache sono reali (misurati alla prima estrazione) ma non implicano
        # nuova spesa: separiamo il conteggio "fatturabile" (chiamate fresche).
        fresh = n - n_cached
        avg_in = tot_in / n if n else 0.0
        avg_out = tot_out / n if n else 0.0
        avg_tok = tot_tok / n if n else 0.0

        price_in = float(rc["pricing_usd_per_million"]["input"])
        price_out = float(rc["pricing_usd_per_million"]["output"])
        cost_sample = (tot_in * price_in + tot_out * price_out) / 1_000_000

        # Estrapolazione al corpus (solo paper con abstract: gli unici estraibili).
        scale = with_abstract / n if n else 0.0
        est_in = avg_in * with_abstract
        est_out = avg_out * with_abstract
        est_cost = (est_in * price_in + est_out * price_out) / 1_000_000

        rpd = int(rc["free_tier"]["rpd"])
        tpm = int(rc["free_tier"]["tpm"])
        days_at_rpd = with_abstract / rpd if rpd else float("inf")
        minutes_at_rpm = with_abstract / rpm if rpm else float("inf")

        print("\n" + "-" * 64)
        print("  MISURATO sul campione (token reali dall'API):")
        print(f"    estrazioni riuscite: {n_done}  | errori: {n_err}")
        print(f"    chiamate fresche: {fresh}  | da cache: {n_cached}")
        print(f"    relazioni estratte: {n_rel}  (abstract con >=1 relazione: {with_rel}/{n})")
        print(f"    parse falliti: {parse_fail}")
        print(f"    token input tot: {tot_in}   (media/abstract: {avg_in:.0f})")
        print(f"    token output tot: {tot_out}  (media/abstract: {avg_out:.0f})")
        print(f"    token totali: {tot_tok}      (media/abstract: {avg_tok:.0f})")
        print(f"    costo campione a listino: ${cost_sample:.4f}")

        print("\n  ESTRAPOLAZIONE al corpus (x{:.1f}, {} paper con abstract):".format(
            scale, with_abstract))
        print(f"    token input stimati: {est_in:,.0f}")
        print(f"    token output stimati: {est_out:,.0f}")
        print(f"    costo stimato a LISTINO (DA VERIFICARE, ${price_in}/${price_out} per 1M): "
              f"${est_cost:.2f}")

        print("\n  FATTIBILITÀ free-tier (limiti in config, DA VERIFICARE):")
        print(f"    {with_abstract} richieste @ {rpm} rpm  -> ~{minutes_at_rpm:.0f} min di wall-clock")
        print(f"    @ {rpd} req/day  -> ~{days_at_rpd:.1f} giorni (limite giornaliero free-tier)")
        print(f"    picco token/min stimato << {tpm:,} tpm? media/abstract={avg_tok:.0f} tok")

        print("\n" + "=" * 64)
        print("  STOP (gate HANDOFF §4): riportati i numeri. Non estendo al corpus")
        print("  né ricostruisco il grafo finché il committente non dà l'OK.")
        print("=" * 64)
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
