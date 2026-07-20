# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-20.

## Dove siamo

**S0 validato (2026-07-20). S1 eseguito: gate PASS 5/7. S2 eseguito: verdetto FAIL.**
Il motore ingest→grafo→closed discovery→time-slicing gira end-to-end e riproducibile,
ma **sul setup attuale il sistema NON batte il baseline a frequenza**. Come da regola di
progetto (DesignArchitecture.md §9), è dichiarato **non funzionante su questo setup** e
**ci si ferma prima di S3**. Servono decisioni del committente (sotto) prima di proseguire.

## Esito S1 — closed discovery (gate PASS, con riserve)

- Gate B noti: **5/7 ritrovati** (IL-6, TNF-α, Treg, Butyrates, LPS). Miss: TLR4, permeabilità (sparsità del corpus campionato).
- Riserva: il ranking grezzo è dominato dai check-tag MeSH (Adult, Mice…); i B noti restano in basso. Presence-based → il PASS regge.

## Esito S2 — time-slicing (verdetto FAIL, onesto)

TEST P@10: **PMI 0.700 vs frequenza 0.900** → il modello non aggiunge valore oltre la frequenza. **Due cause reali:**
1. **Finestra DEV (≤2010) strutturalmente vuota sul lato A.** I descrittori MeSH del microbioma ("Gastrointestinal Microbiome", "Dysbiosis") sono entrati in MeSH ~2012-2014: corridoio A = **2 paper ≤2010**, 152 ≤2015. N non tarabile → default N=1 → hit banale → la frequenza domina.
2. **Grafo di sola co-occorrenza:** senza il layer relazionale reale (SemMedDB o estrazione LLM grounded) non c'è un segnale di specificità che batta la frequenza. È la tesi stessa del progetto: serve un filtro più intelligente.

Nessun tentativo di "aggiustare" la metrica per forzare un PASS (sarebbe p-hacking, vietato dai principi).

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

## Prossimo passo — DECISIONE DEL COMMITTENTE (S2 non passato, S3 bloccato)

Il gate S2 blocca S3. Per sbloccare servono scelte tue, in ordine di leva:

1. **Correggere le finestre di time-slicing** (config `time_slicing`): con vocabolario MeSH post-2012, DEV ≤2010 è invalido. Proposta: DEV cutoff ~2018 / eval 2019-2021, TEST cutoff ~2021 / eval 2022-2025. È una decisione metodologica: non l'ho cambiata da solo.
2. **Aggiungere il layer relazionale reale** (la vera leva sul filtro):
   - **Estrazione LLM grounded** → serve `ANTHROPIC_API_KEY` (+ stima costo su 100 abstract).
   - **SemMedDB** → serve licenza UMLS (richiesta in parallelo).
3. **Ingrandire/ribilanciare il corpus** (alzare `per_year_cap`, o restringere il corridoio a finestre dove A esiste).
4. (Refinement) `first_year` PubDate vs `pdat`; PubTator3 come sorgente entità/relazioni.

Finché non decidi 1+2, il verdetto resta FAIL e non si procede a S3/S4/S5.

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
