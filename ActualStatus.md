# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-20.

## Dove siamo

**S0 completato e validato dal committente (2026-07-20).** Lo strato di ingest funziona end-to-end: corpus pilota A↔C scaricato, normalizzato e cacheato in modo riproducibile. Prossimo sprint: **S1 (grafo + closed discovery)**.

## Fatto in questa sessione (2026-07-20)

- Ambiente: venv + dipendenze runtime installate (biopython, requests, networkx, pyyaml, python-dotenv, anthropic).
- `engine/src/ingest/cache.py`: cache SQLite Tier-1 (schema `DesignArchitecture.md §6.1`) + `eutils_cache` per il re-run offline.
- `engine/src/ingest/entrez_client.py`: client E-utilities (esearch/efetch), rate limiting 10 req/s, retry con backoff sui soli errori transitori, key/mail da env, parsing robusto di data/abstract/journal.
- `engine/src/ingest/download_corpus.py`: runner config-driven; **campionamento per-anno** (non piatto) per coprire DEV/TEST; registra la run in `pipeline_runs`; stampa il report.
- `pilot.yaml`: parametri di sampling (`sampling`, `per_year_cap`, `max_year`) — niente hardcoded.
- `pyproject.toml`: override mypy per librerie non tipizzate (Bio, yaml) + `mypy_path`.
- Test di parsing (`engine/tests/`, offline) + `conftest.py`.
- **Corpus:** 4061 paper (86.9% con abstract), 1990–2026, finestre DEV/TEST popolate. Numeri completi in `Sprint_Done.md`.
- Commit su `claude/status-update-erivcz`, pushato. Verifiche verdi: ruff, mypy --strict, pytest.

## Dove risiedono i dati (importante)

- La cache `engine/data/cache.sqlite` (~80 MB, i 4061 paper) è **gitignored** e **non versionata**. In questa sessione vive sul disco del **container cloud effimero** di Claude Code: si perde a fine sessione, ma è **ricostruibile deterministicamente** rilanciando l'ingest.
- Il motore è **local-first**: girato sulla macchina del committente, l'ingest è a **costo zero e senza sviluppo aggiuntivo** (Python + deps + `NCBI_API_KEY` nel `.env` + `python -m ingest.download_corpus`).
- **Nessun abstract grezzo andrà mai su Supabase** (copyright editori). Supabase (S4) riceve solo il subset curato/derivato su ID aperti.

## Decisioni architetturali chiuse

- Motore **local-first** Python: NetworkX (calcolo) + SQLite (cache grezza, gitignored).
- Entità: **PubTator3 + MeSH** → grafo **multi-ontologia**.
- Relazioni: **SemMedDB** (UMLS) con **fallback** (co-occorrenza + PubTator3 rel + LLM grounded) dietro `RelationSource`.
- **Guardrail LLM**: solo estrazione grounded, mai giudizio di plausibilità (anti-contaminazione time-slicing).
- Pubblicazione: **Supabase/Postgres** (solo subset curato, ID aperti) + web **Next.js** (Cytoscape/Sigma). **Niente Neo4j.**
- Time-slicing: DEV (≤2010→2011-2015) / TEST (≤2015→2016-2025); **terzo asse predisposto nel config**, non attivo.
- Ingest: **campionamento per-anno** (cap per anno/corridoio) per non biasare il corpus verso i paper recenti.
- Embeddings SPECTER2/FAISS **rimandati a S3**.

## Decisioni esterne PENDENTI (dal committente)

1. **UMLS/SemMedDB** — avviare la richiesta licenza in parallelo (non blocca: si parte col fallback).
2. **LLM estrazione** — modello scelto dopo **stima di costo su 100 abstract** (in S1). L'`ANTHROPIC_API_KEY` non è ancora impostata.
3. **Slot Supabase** — decidere upgrade Pro (~$25/mese) vs riorganizzazione; serve solo da **S4**.

## Prossimo passo — S1 (grafo + closed discovery)

- Definizione operativa di **`first_year`** (PubDate vs `pdat` vs earliest): decisione aperta emersa in S0.
- `pubtator_client.py` (entità + relazioni PubTator3, cacheate); nodi MeSH per i concetti non coperti.
- Costruzione `MultiDiGraph`; `RelationSource` + fallback; stima costo LLM su 100 abstract → scelta modello.
- `closed_discovery.py`: verificare che ritrovi ≥ 5 dei 7 B noti. **Gate bloccante**: se < 5, fermarsi.

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
