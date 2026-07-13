# ActualStatus — Swanson Project

> Stato corrente per allineare le sessioni senza riesaminare il codice. Leggere **per primo**, insieme a `Sprint.md`.
> Ultimo aggiornamento: 2026-07-13.

## Dove siamo

**Fase di fondazione (parte di S0) completata.** Definita insieme al committente l'architettura, generata tutta la documentazione, inizializzato il repository. Non ancora scritta una riga del motore: si attende la risoluzione di alcune decisioni esterne (sotto) prima di S0-implementazione (download corpus).

## Fatto in questa sessione (2026-07-13)

- `git init` + struttura monorepo: `engine/{src/{ingest,graph,discovery,validation,export,publish},config,tests,data}`, `web/`, `supabase/`.
- Documentazione riscritta da zero per questo progetto (i file ereditati erano di **GuesTrace**): `AGENTS.md`, `Project.md`, `DesignArchitecture.md`, `Sprint.md`, `Sprint_Done.md` (azzerato), `README.md`.
- Scaffolding: `.gitignore`, `.env.example`, `engine/pyproject.toml`, `engine/config/pilot.yaml`, `web/README.md`, `supabase/README.md`.
- Tentata creazione progetto Supabase `swanson-lbd` → **bloccata**: limite free-tier di 2 progetti per l'organizzazione (già `guestrace` + `firetrace`).

## Decisioni architetturali chiuse

- Motore **local-first** Python: NetworkX (calcolo) + SQLite (cache grezza, gitignored).
- Entità: **PubTator3 + MeSH** → grafo **multi-ontologia**.
- Relazioni: **SemMedDB** (UMLS) con **fallback** (co-occorrenza + PubTator3 rel + LLM grounded) dietro `RelationSource`.
- **Guardrail LLM**: solo estrazione grounded, mai giudizio di plausibilità (anti-contaminazione time-slicing).
- Pubblicazione: **Supabase/Postgres** (solo subset curato, ID aperti) + web **Next.js** (Cytoscape/Sigma). **Niente Neo4j.**
- Time-slicing: DEV (≤2010→2011-2015) / TEST (≤2015→2016-2025); **terzo asse predisposto nel config**, non attivo.
- Embeddings SPECTER2/FAISS **rimandati a S3**.

## Decisioni esterne PENDENTI (dal committente) — sbloccano S0-impl

1. **NCBI API key** — da ottenere (account NCBI → Account Settings → API Key Management, gratis/immediata) e mettere in `.env`. **Prerequisito bloccante per il download del corpus.**
2. **UMLS/SemMedDB** — avviare la richiesta in parallelo (l'assistente prepara il testo). Non blocca: si parte col fallback.
3. **LLM estrazione** — modello scelto dopo **stima di costo su 100 abstract** (in S1).
4. **Slot Supabase** — decidere upgrade Pro (~$25/mese) vs riorganizzazione; comunque non serve prima di **S4**.

## Prossimo passo

S0-implementazione: venv + dipendenze (previa conferma), client E-utilities + cache SQLite, rifinitura query MeSH, download del corpus pilota (~3–5k abstract). Richiede la **NCBI API key**.

## Note

- Non toccare i progetti Supabase `guestrace`/`firetrace` (produzione).
- `CLAUDE.md` → include `AGENTS.md`. `token-optimization.md` invariato e valido.
