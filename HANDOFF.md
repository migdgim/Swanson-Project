# HANDOFF — passaggio al Claude Code locale (Mac)

> Istruzioni per riprendere il progetto in locale, sul disco del committente, con dati persistenti.
> Leggere **insieme a** `ActualStatus.md` e `Sprint.md`.

## Stato al passaggio (2026-07-20)

- **S0** (ingest corpus): fatto e validato. Corpus pilota A↔C = 4061 paper, riproducibile.
- **S1** (grafo + closed discovery): gate B noti **PASS 5/7**.
- **S2** (time-slicing): **verdetto FAIL pulito** — la sola co-occorrenza non batte il
  baseline a frequenza (TEST P@10: PMI 0.100 vs frequenza 0.800). Finestre già corrette
  (DEV ≤2018 / TEST ≤2021). Dettagli e diagnosi in `ActualStatus.md`.
- Branch di lavoro: **`claude/status-update-erivcz`** (tutto è qui, non su `main`).
- La cache dati (`engine/data/cache.sqlite`) è gitignored e NON versionata: si **rigenera**
  con `download_corpus` (deterministico). In locale resterà sul disco, persistente.

## Setup locale (una volta)

Dalla cartella del progetto:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install biopython requests networkx pyyaml python-dotenv anthropic
```

Crea `.env` (copia da `.env.example`, resta sul disco, è gitignored):

```
NCBI_API_KEY=...        # già in uso
NCBI_EMAIL=migdgim@gmail.com
GEMINI_API_KEY=...       # scelto dal committente per l'estrazione relazioni (S3-prep)
```

## Riprodurre lo stato attuale

```bash
cd engine/src
python -m ingest.download_corpus         # rigenera il corpus sul disco (~2 min)
python -m discovery.run_closed_discovery # S1: gate B noti (atteso 5/7 PASS)
python -m validation.run_time_slicing    # S2: verdetto (atteso FAIL)
```

Verifiche backend: `cd engine && ruff check src tests && mypy --strict src tests conftest.py && python -m pytest -q`.

## Prossimo obiettivo — layer relazionale reale (la leva per battere la frequenza)

Il committente ha scelto **Gemini** (ha la key gratuita). Compito:

1. Aggiungere la dipendenza `google-generativeai` (chiedere conferma prima di installare —
   regola di progetto; il committente ha già dato l'OK a Gemini).
2. Definire l'interfaccia `RelationSource` (Protocol) e un'implementazione LLM con Gemini che
   **estragga SOLO relazioni presenti nel testo dell'abstract** (triple soggetto–predicato–oggetto).
   **Guardrail non negoziabile:** l'LLM non deve MAI giudicare la plausibilità di un legame
   A–B–C (contaminerebbe il time-slicing). Solo estrazione grounded.
3. Determinismo: temperatura 0, ogni risposta LLM **cacheata su disco** (tabella `llm_extractions`,
   chiave sul prompt), re-run offline.
4. Fare **prima** la stima di costo/fattibilità su **100 abstract** (limiti free tier Gemini),
   riportare i numeri, poi decidere se estendere al corpus.
5. Ricostruire il grafo con le relazioni estratte e **ri-eseguire S2** per vedere se il verdetto
   cambia. Riportare i numeri onestamente (nessun p-hacking; se resta FAIL, dirlo).

## Regole di progetto da rispettare (da `AGENTS.md`)

- 1 sprint = 1 sessione: a fine sprint fermarsi, riportare i numeri, attendere l'OK prima di
  commit/push e prima del successivo.
- Niente stub/dati finti/numeri inventati; ogni metrica da codice eseguito.
- Nessuna dipendenza nuova senza chiedere (Gemini già approvata).
- Config in `engine/config/pilot.yaml`, mai hardcoded.
- Lavorare solo dentro la project root; non toccare `.env`, né i progetti `guestrace`/`firetrace`.
- Sviluppare sul branch `claude/status-update-erivcz`; push su quello.
