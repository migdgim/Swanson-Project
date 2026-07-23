# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-23.

## Dove siamo

**PILOTA CHIUSO (2026-07-23), con conclusione onesta.** Il motore gira end-to-end e
riproducibile su tutta la pipeline: ingest → grafo → closed discovery → estrazione
relazionale LLM (2397/2397, grounded) → time-slicing → open discovery. **Verdetto: il
layer relazionale NON batte il baseline a frequenza in modo dimostrabile su questo corpus.**

Percorso dei verdetti (tutti eseguiti, TEST una volta sola, matching plain uniforme):
1. **Closed S2, co-occorrenza** (baseline): FAIL — P@10 PMI 0.100 vs freq **0.800**.
2. **Closed S2, grounding come segnale**: FAIL — grounded 0.000 vs freq **0.800**. La frequenza
   domina *per tautologia* (hit N≥1 = persistenza dei termini frequenti).
3. **Open discovery** (reframe anti-tautologia): FAIL ma informativo — grounded **0.200** vs
   freq **0.300** vs random 0.000. Il reframe abbatte la tautologia (freq 0.800→0.300); il
   grounded ha segnale **non casuale ma non superiore** alla frequenza. **Sotto-potenziato**
   (29-38 hit, P@10 rumoroso ±0.1).

**Lettura onesta:** su un campione di 4061 paper il segnale grounded esiste (i suoi top
candidati — Prebiotics, Bifidobacterium, Melanoma… — sono biologicamente sensati, *come
osservazione non come metrica*: guardrail rispettato) ma è penalizzato da limiti **noti e
fixabili** — potenza statistica (più corpus) e copertura del matching menzione→MeSH
(sinonimi uniformi / PubTator3). Nessun p-hacking: task e verdetti pre-registrati.

**Il pilota si chiude qui** per decisione del committente. Se si riprende, le leve sono in
"Se si riprende" più sotto.

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

## Fatto in questa sessione (2026-07-23) — estrazione completa + S2-rerun + open discovery (CHIUSURA)

- **Pin del modello LLM:** `gemini-3.1-flash-lite` (`3.1-flash-lite-05-2026`) in `pilot.yaml` e `.env`. L'alias `-latest` era driftato 3.1→3.5 tra il 21 e il 23/07 → pin per coerenza del corpus. Le 991 estrazioni del 21/07 rietichettate in cache (backup `cache.sqlite.bak-prepin`).
- **Estrazione completata:** billing Google attivato (€10) → throttle a 60 rpm, no più RPD. **2397/2397** paper pre-cutoff, 0 errori, **8.920 relazioni**. Costo: pochi centesimi.
- **Grafo relazionale grounded** (`build_graph.py` modalità grounded) + **ri-esecuzione S2** con il grounding come *segnale di ranking* (non filtro) → FAIL (freq tautologica 0.800).
- **Open discovery time-sliced** (nuovo: `validation/run_open_discovery.py`, `OpenSlice`/`build_open_slices`/`evaluate_open_split`): candidato = mezzo-ponte, hit = chiusura del lato mancante. Reframe **pre-registrato** → FAIL ma informativo (grounded 0.200 vs freq 0.300, tautologia abbattuta).
- **Verifiche verdi:** ruff, mypy --strict (7 file), 21 test. Vedi `Sprint_Done.md` per i dettagli completi.

## Fatto nella sessione del 2026-07-21 — layer relazionale LLM + ripresa locale

- **Ambiente locale (Mac):** Homebrew + Python 3.12, venv, dipendenze runtime + `google-generativeai` (approvata). Cache 4061 paper **rigenerata sul disco del committente** (persistente). Pipeline riprodotta: **S1 5/7 PASS, S2 FAIL** (identici allo stato registrato).
- **`relations/` (nuovo modulo):** interfaccia `RelationSource` (Protocol, `DesignArchitecture.md §7`) + `GeminiRelationSource` grounded (temp 0, cache su disco `llm_extractions`, rate limiting, token misurati). Prompt versionato `v1` con **guardrail anti-contaminazione** (solo estrazione, mai plausibilità). Runner `estimate_cost.py` e `extract_corpus.py` (riprendibile).
- **Stima costo su 100 abstract (eseguita):** 410 relazioni, 910 token/abstract, **$0 sul free tier**. Estrazione pre-cutoff (2397 paper ≤2021) ~5 giorni a scatti, riprendibile. Dettaglio in `Sprint_Done.md`.
- **Modello LLM scelto:** `gemini-flash-lite-latest` (= Gemini 3.1 Flash Lite): unico free con RPD alto (500). `gemini-1.5/2.5-*` ritirati/non accessibili a key nuove. Alias: da fissare per riproducibilità piena prima del run intero.
- **Limiti free-tier verificati** (dashboard AI Studio, 2026-07-21): RPM 15 · TPM 250K · RPD 500 → nel config (client throttle a 12 rpm per margine).
- **Normalizzazione (de-risking, scelta MeSH):** costruito il layer menzione→descrittore MeSH (`relations/normalize.py`), i sinonimi/entry-terms MeSH via Entrez cacheati (`relations/mesh_synonyms.py`, tabella `mesh_synonyms`) e un report di copertura (`relations/coverage_report.py`). **Risultato onesto** (su 618 paper parziali, pmid vecchi, non rappresentativi): i sinonimi funzionano dove servono (IL-6 2/4→3/4, Treg 0/1→1/1); TNF-α resta 0/5 ma **per lo più correttamente** — 3/5 sono tag MeSH senza relazione affermata nell'abstract (il *filtro* che scarta la co-occorrenza nuda, cioè l'effetto voluto), 2/5 sono un limite residuo del match su acronimi nudi (TNF/LPS). Approccio giudicato **sano**; nessuna ottimizzazione forzata del matcher (sarebbe p-hacking sul campione).
- **In corso/da fare:** completare l'estrazione pre-cutoff, poi **costruzione grafo relazionale → ri-esecuzione S2** (verdetto vero solo a copertura sufficiente).

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
2. ~~**LLM estrazione** — modello scelto + alias pinnato~~ **CHIUSO (2026-07-23):** Gemini 3.1 Flash Lite. **Alias pinnato** su `gemini-3.1-flash-lite` (`3.1-flash-lite-05-2026`) in `pilot.yaml` **e** in `.env` (`GEMINI_MODEL`). Motivo: l'alias mobile `gemini-flash-lite-latest` è **driftato 3.1→3.5** tra il 21 e il 23 luglio (verificato: 6 triple con 3.1 vs 1 con 3.5 sullo stesso abstract) → con un run multi-giorno avrebbe mescolato due modelli. Le 991 estrazioni del 21/07 rietichettate in cache (991/991, cache-hit confermati; backup `engine/data/cache.sqlite.bak-prepin`). Billing attivato (€10) per completare l'estrazione senza il tetto RPD. Corpus uniforme e riproducibile.
3. **Slot Supabase** — decidere upgrade Pro (~$25/mese) vs riorganizzazione; serve solo da **S4**.

## Se si riprende (pilota chiuso — leve, in ordine di priorità)

Il pilota è chiuso con verdetto FAIL onesto. Le leve provate sono esaurite (co-occorrenza,
grounding come filtro, grounding come segnale, open discovery: tutte eseguite). Ciò che resta
NON è più "un'altra metrica" ma **investimenti su dati e copertura**, motivati dai risultati:

1. **Potenza statistica → più corpus.** 29-38 hit rendono P@10 rumoroso (±0.1). Alzare `per_year_cap` / estendere l'ingest darebbe un verdetto robusto (l'open discovery è già pronto e riproducibile).
2. **Copertura del grounded → sinonimi uniformi o PubTator3.** Il matching menzione→MeSH plain perde nomi formali (Treg, TNF-α). L'espansione entry-terms MeSH **uniforme** (già in `mesh_synonyms.py`, ma applicarla a *tutti* i descrittori, non solo ai B noti) o PubTator3 (ID normalizzati, zero match a stringhe) alzerebbe il segnale grounded.
3. **SemMedDB** come `RelationSource` primaria → serve licenza UMLS.
4. (Refinement minori) `first_year` PubDate vs `pdat`.

**Guardrail invariato:** qualunque ripresa resta time-sliced e grounded; mai far giudicare
la plausibilità di un legame all'LLM (contaminazione).

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
