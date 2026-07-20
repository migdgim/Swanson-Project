# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-21.

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

**Prima esecuzione** (finestre DEV ≤2010 / TEST ≤2015): FAIL, ma confuso da un problema strutturale — la DEV era **vuota sul lato A** (i descrittori MeSH del microbioma sono entrati in MeSH ~2012-2014: corridoio A = 2 paper ≤2010).

**Seconda esecuzione** (finestre corrette DEV ≤2018 / TEST ≤2021, A=376/607 pre-cutoff — valide): **FAIL pulito**. TEST P@10: **PMI 0.100 vs frequenza 0.800**. Non è più un artefatto: la co-occorrenza nuda con metrica di specificità **non batte la frequenza**.

Interpretazione onesta:
1. Il **grafo di sola co-occorrenza** non offre un segnale che batta la frequenza. Serve il layer relazionale reale (estrazione LLM grounded / SemMedDB).
2. Sottigliezza metodologica: con hit=N≥1 la frequenza è quasi tautologicamente "hit" (i termini frequenti persistono). La definizione di hit / il task (valutazione closed vs open discovery) andrà raffinata — decisione del committente.

Nessun tentativo di "aggiustare" la metrica per forzare un PASS (sarebbe p-hacking, vietato dai principi).

## Fatto in questa sessione (2026-07-21) — layer relazionale LLM + ripresa locale

- **Ambiente locale (Mac):** Homebrew + Python 3.12, venv, dipendenze runtime + `google-generativeai` (approvata). Cache 4061 paper **rigenerata sul disco del committente** (persistente). Pipeline riprodotta: **S1 5/7 PASS, S2 FAIL** (identici allo stato registrato).
- **`relations/` (nuovo modulo):** interfaccia `RelationSource` (Protocol, `DesignArchitecture.md §7`) + `GeminiRelationSource` grounded (temp 0, cache su disco `llm_extractions`, rate limiting, token misurati). Prompt versionato `v1` con **guardrail anti-contaminazione** (solo estrazione, mai plausibilità). Runner `estimate_cost.py` e `extract_corpus.py` (riprendibile).
- **Stima costo su 100 abstract (eseguita):** 410 relazioni, 910 token/abstract, **$0 sul free tier**. Estrazione pre-cutoff (2397 paper ≤2021) ~5 giorni a scatti, riprendibile. Dettaglio in `Sprint_Done.md`.
- **Modello LLM scelto:** `gemini-flash-lite-latest` (= Gemini 3.1 Flash Lite): unico free con RPD alto (500). `gemini-1.5/2.5-*` ritirati/non accessibili a key nuove. Alias: da fissare per riproducibilità piena prima del run intero.
- **Limiti free-tier verificati** (dashboard AI Studio, 2026-07-21): RPM 15 · TPM 250K · RPD 500 → nel config (client throttle a 12 rpm per margine).
- **In corso/da fare:** estrazione relazioni sul pre-cutoff, poi **normalizzazione entità → grafo → ri-esecuzione S2**.

## Fatto nella sessione precedente (2026-07-20)

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
2. ~~**LLM estrazione** — modello scelto dopo stima di costo su 100 abstract~~ **DECISO (2026-07-21):** Gemini 3.1 Flash Lite (free tier, $0), key AI Studio impostata. Resta da: fissare l'alias su un modello pinnato per riproducibilità prima del run sul corpus intero.
3. **Slot Supabase** — decidere upgrade Pro (~$25/mese) vs riorganizzazione; serve solo da **S4**.

## Prossimo passo — DECISIONE DEL COMMITTENTE (S2 non passato, S3 bloccato)

Il gate S2 blocca S3. Per sbloccare servono scelte tue, in ordine di leva:

1. ~~Correggere le finestre di time-slicing~~ **FATTO (2026-07-20)**: DEV ≤2018 / TEST ≤2021. Ha rimosso il confound (DEV vuota) → il FAIL è ora pulito.
2. **Aggiungere il layer relazionale reale** (la vera leva sul filtro):
   - **Estrazione LLM grounded** → serve una API key LLM. **Va bene anche Gemini** (task = estrarre relazioni dal testo dell'abstract): richiede una nuova dipendenza (`google-generativeai`) e un'implementazione `RelationSource` LLM, con lo stesso guardrail anti-contaminazione. In alternativa Anthropic (`ANTHROPIC_API_KEY`, dep `anthropic` già presente).
   - **SemMedDB** → serve licenza UMLS (richiesta in parallelo).
3. **Raffinare la definizione di hit / il task di validazione** (con N≥1 la frequenza è quasi tautologica): valutare open discovery o hit più stringente. Decisione metodologica del committente.
4. (Refinement) `first_year` PubDate vs `pdat`; PubTator3 come sorgente entità/relazioni; alzare `per_year_cap`.

Finché non si affronta il punto 2 (+ eventualmente 3), il verdetto resta FAIL e non si procede a S3/S4/S5.

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
