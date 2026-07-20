# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-20.

## Dove siamo

**S0 in corso.** La fondazione è chiusa (repo, struttura, documentazione — sessione 2026-07-13). In questa sessione (2026-07-20) è stato **scritto e testato** il primo codice del motore (ingest): cache SQLite, rate limiter, client E-utilities. **41 test verdi, eseguiti.** Il download del corpus è però **bloccato dalla network policy dell'ambiente** (l'egress verso NCBI è negato: 403 dal proxy). Non è un problema di codice né di chiave: è configurazione dell'ambiente cloud. Vedi **Blocco attuale**.

## Fatto in questa sessione (2026-07-20)

- **Ricevuta la NCBI API key** dal committente. Creato `.env` (gitignored) con `NCBI_API_KEY` + `NCBI_EMAIL`.
- **venv + dipendenze installate** con `pip install -e "./engine[dev]"` (biopython 1.87, requests, networkx, pyyaml, python-dotenv, anthropic, + pytest/ruff/mypy). NB: container **effimero** → da ri-eseguire ogni sessione (o via setup script dell'ambiente).
- **Codice ingest scritto** (commit `d0f6e8d` sul branch `claude/stato-prossimi-passi-81e6rt`):
  - `engine/src/ingest/cache.py` — cache Tier-1 su SQLite (schema `DesignArchitecture.md §6.1`), idempotente, con `year_counts()`. Solo stdlib. **Eseguito e testato.**
  - `engine/src/ingest/rate_limiter.py` — intervallo minimo (10 req/s con key, 3 senza), clock iniettabile. Riusabile per PubTator3. **Eseguito e testato.**
  - `engine/src/ingest/entrez_client.py` — client E-utilities (`esearch → efetch → cache`), retry con backoff, parsing date/abstract, `download_corpus()`. **Parsing e orchestrazione testati; il layer di rete (`Bio.Entrez`) NON è stato eseguito** (bloccato dall'egress).
  - `engine/tests/` — 41 test (`unittest`, girano anche sotto pytest), tutti verdi.
- **Provata la connettività a NCBI → 403 Forbidden dal proxy** (host `eutils.ncbi.nlm.nih.gov` non in allowlist). Non ritentato/aggirato (da regole del proxy).

## Blocco attuale — network egress verso NCBI (azione del committente)

L'ambiente cloud non è autorizzato a raggiungere NCBI. Sblocco (lato committente, su claude.ai/code):
- Selettore ambiente (icona a nuvola) → **hover sulla riga dell'ambiente → ingranaggio ⚙** → dialog di modifica.
- **Network access → Custom** → **Allowed domains**: `*.ncbi.nlm.nih.gov` (copre `eutils` per S0 e `www` per PubTator3/S1).
- **Spuntare "Also include default list of common package managers"** (altrimenti si perde pip/PyPI → il venv non si ricostruisce).
- *(Consigliato)* Nella stessa dialog, **Environment variables**: `NCBI_API_KEY=...` e `NCBI_EMAIL=...` → iniettate in ogni sessione, così non serve ricreare `.env` a mano.
- Salvare e **avviare una sessione NUOVA** (le policy si applicano all'avvio del container).

## Decisioni architetturali chiuse

- Motore **local-first** Python: NetworkX (calcolo) + SQLite (cache grezza, gitignored).
- Entità: **PubTator3 + MeSH** → grafo **multi-ontologia**.
- Relazioni: **SemMedDB** (UMLS) con **fallback** (co-occorrenza + PubTator3 rel + LLM grounded) dietro `RelationSource`.
- **Guardrail LLM**: solo estrazione grounded, mai giudizio di plausibilità (anti-contaminazione time-slicing).
- Pubblicazione: **Supabase/Postgres** (solo subset curato, ID aperti) + web **Next.js** (Cytoscape/Sigma). **Niente Neo4j.**
- Time-slicing: DEV (≤2010→2011-2015) / TEST (≤2015→2016-2025); **terzo asse predisposto nel config**, non attivo.
- Embeddings SPECTER2/FAISS **rimandati a S3**.

## Decisioni esterne PENDENTI (dal committente)

1. **Network egress NCBI** — **NUOVO BLOCCANTE per il download.** Vedi *Blocco attuale* sopra. (La NCBI API key è già stata ottenuta e configurata.)
2. **Strategia di assemblaggio del corpus** — da decidere sui **conteggi reali** (leggibili solo a egress aperto). Nodo aperto: A e C vanno scaricati separati; C (`Neoplasms`) è enorme → serve **campionamento stratificato per anno** per non affamare la finestra DEV (≤2010). `retmax`/campionamento si fissano dopo aver visto i Count veri.
3. **UMLS/SemMedDB** — avviare la richiesta in parallelo (l'assistente prepara il testo). Non blocca: si parte col fallback.
4. **LLM estrazione** — modello scelto dopo **stima di costo su 100 abstract** (in S1).
5. **Slot Supabase** — upgrade Pro (~$25/mese) vs riorganizzazione; non serve prima di **S4**.

## Prossimo passo (nella sessione nuova, a egress aperto)

1. `git checkout claude/stato-prossimi-passi-81e6rt`; ricreare venv (`pip install -e "./engine[dev]"`); ricreare `.env` se non si usano le env var dell'ambiente.
2. **Confermare la connettività** a NCBI con un `esearch` di prova (Count su A/C via `EntrezClient.from_env()`).
3. **Misurare i Count reali** di A, C, A∧C per finestra temporale → riportarli al committente.
4. Decidere insieme `retmax` + campionamento → **scaricare il corpus** (`download_corpus`, chiamato per A e per C).
5. Ispezione: **conteggi per anno** → report. Solo a quel punto S0 si chiude.

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
- Progetto Supabase `swanson-lbd` ancora **non creato** (rinviato a S4; limite free-tier).
