# Sprint — Swanson Project

> Sprint futuri e task da fare. Caricamento automatico a ogni sessione.
> **Principio: 1 sprint = 1 sessione** (verticale, autonomamente testabile dal backend).
> A sprint validato dal committente: marcare `[x]`, datare, spostare in `Sprint_Done.md`.
> Ultimo aggiornamento: 2026-07-20.

**Stato:** **S0 in corso.** Ingest scritto e testato (cache SQLite, rate limiter, client E-utilities; 41 test verdi — commit `d0f6e8d`). NCBI API key ottenuta. **Download bloccato dalla network policy dell'ambiente** (egress verso NCBI negato, 403): sbloccare con Custom allowlist `*.ncbi.nlm.nih.gov` + package managers, poi sessione nuova. Progetto Supabase **rinviato a S4** (limite free-tier). Dettaglio e ripartenza in `ActualStatus.md`.

---

## S0 — Fondazioni

**Obiettivo:** scaricare, normalizzare e cacheare il corpus pilota, in modo riproducibile.

- [x] `git init`, struttura monorepo (`engine/`, `web/`, `supabase/`), `.gitignore`, `.env.example`
- [x] Documentazione allineata (AGENTS, Project, DesignArchitecture, Sprint, ActualStatus)
- [x] `engine/config/pilot.yaml` (query MeSH A/C, B noti, finestre DEV/TEST, parametri)
- [x] `pyproject.toml` → venv + install dipendenze runtime — *eseguito 2026-07-20 (`pip install -e "./engine[dev]"`); container effimero → da ri-eseguire ogni sessione, o via setup script*
- [x] Cache SQLite (`ingest/cache.py`): schema Tier-1, ogni risposta grezza persistita — *scritta e testata (18 test verdi)*
- [x] Rate limiter (`ingest/rate_limiter.py`): 10 req/s con key, 3 senza — *scritto e testato (5 test verdi); riusabile per PubTator3*
- [~] Client E-utilities (`ingest/entrez_client.py`): API key da `.env`, rate limiting, retry — *scritto; parsing+orchestrazione testati (18 test). **Layer di rete NON eseguito**: egress NCBI bloccato*
- [ ] **Sbloccare egress NCBI** (network policy ambiente) → **BLOCCANTE per il download**
- [ ] Misurare i Count reali (A, C, A∧C per finestra) → decidere `retmax` + campionamento stratificato per anno
- [ ] Rifinitura query MeSH del corridoio; download ~3–5k abstract del corpus A↔C (`download_corpus` per A e per C)
- [ ] Ispezione: conteggi per anno, sanity check sul corpus

**Deliverable:** corpus scaricato e cacheato; re-run offline funzionante; report a una riga con i conteggi.
**Prerequisito bloccante:** ~~NCBI API key~~ (ottenuta) → **egress di rete verso NCBI abilitato** nell'ambiente.
**Gate:** stop & report — numeri del corpus.

---

## S1 — Grafo + Closed Discovery

**Obiettivo:** costruire il grafo multi-ontologia e verificare che il sistema ritrovi i B già noti.

- [ ] `ingest/pubtator_client.py`: entità normalizzate + relazioni PubTator3 (cacheate)
- [ ] Nodi MeSH per i concetti non coperti (Treg, permeabilità intestinale, ...)
- [ ] `graph/`: costruzione `MultiDiGraph`, nodi tipizzati, edges pesati con PMID + `first_year`
- [ ] `RelationSource` (interfaccia) + implementazione **fallback** (co-occorrenza + PubTator3 rel)
- [ ] **Stima di costo LLM su 100 abstract** → report costo per l'intero corpus → scelta modello (Haiku/Sonnet)
- [ ] Estrazione LLM grounded delle relazioni (con guardrail anti-contaminazione), cacheata
- [ ] `discovery/closed_discovery.py`: dati A e C, ritrova i B
- [ ] Test: closed discovery ritrova ≥ 5 dei 7 B noti

**Gate BLOCCANTE:** se ritrova < 5 B noti, **fermati e riportalo** — non proseguire a S2.

---

## S2 — Time-Slicing

**Obiettivo:** verdetto binario sul potere predittivo.

- [ ] `validation/time_slicing.py`: maschera temporale sul grafo; guardia DEV/TEST non aggirabile
- [ ] Definizione operativa dell'hit (≥ N predicazioni A–B e B–C post-cutoff), N tarato su DEV
- [ ] Baselines: frequenza pura + random
- [ ] Metriche: precision@{10,25,50}, recall, falsi positivi top-10 espliciti
- [ ] Taratura soglie/metriche **solo su DEV**; poi esecuzione **una volta** su TEST
- [ ] Report: numeri reali, confronto coi baseline, verdetto pass/fail

**Gate:** se non batte il baseline a frequenza → sistema non funzionante, dichiararlo. Non si prosegue a S3 senza pass.

---

## S3 — Ranking avanzato + Open Discovery

**Obiettivo (solo se S2 passa):** alzare la precisione e generare ipotesi nuove.

- [ ] Install gruppo `semantic` (torch, transformers, adapters, faiss-cpu) — previa conferma
- [ ] Embeddings SPECTER2 + indice FAISS (cacheati)
- [ ] Metrica di novità semantica; confronto con TF-IDF/PMI sul DEV set; scelta documentata
- [ ] `discovery/open_discovery.py`: B candidati nuovi sul corridoio pilota
- [ ] Ranking finale rivalidato

**Gate:** stop & report — ranking e metriche.

---

## S4 — Pubblicazione

**Obiettivo:** rendere pubblico il subset curato.

- [ ] Decisione slot Supabase (upgrade Pro vs riorganizzazione) + creazione progetto `swanson-lbd`
- [ ] Schema pubblico (migrazioni via MCP) + RLS lettura pubblica
- [ ] `publish/`: mapping snapshot curato → ID aperti → Supabase (solo dati derivati, no righe UMLS)
- [ ] `export/`: Markdown/Obsidian del solo subset finale
- [ ] Verifica backend: RLS, integrità, advisors

**Gate:** stop & report.

---

## S5 — Web UI pubblica

**Obiettivo:** interfaccia consultabile dai ricercatori.

- [ ] `web/` Next.js su Vercel; connessione Supabase (anon, sola lettura)
- [ ] Esploratore grafo (Cytoscape.js/Sigma.js)
- [ ] Pagine-ipotesi con evidenze (PMID)
- [ ] Report di validazione in chiaro (trasparenza scientifica)

**Gate:** verifica UI a carico del committente.

---

## Backlog / futuro (non ora)

- Terzo asse temporale del time-slicing (finestra intermedia / valutazione a scorrimento)
- Innesto SemMedDB come `RelationSource` primaria (a licenza UMLS ottenuta)
- Nuovi corridoi A→C oltre il pilota microbioma-cancro
