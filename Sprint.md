# Sprint — Swanson Project

> Sprint futuri e task da fare. Caricamento automatico a ogni sessione.
> **Principio: 1 sprint = 1 sessione** (verticale, autonomamente testabile dal backend).
> A sprint validato dal committente: marcare `[x]`, datare, spostare in `Sprint_Done.md`.
> Ultimo aggiornamento: 2026-07-20.

**Stato:** **S0 completato e validato** (2026-07-20) — ingest del corpus pilota funzionante (4061 paper, 1990–2026, riproducibile offline). Dettaglio in `Sprint_Done.md`. Progetto Supabase **rinviato a S4** per il limite free-tier (2 progetti già occupati da `guestrace`/`firetrace`). Prossimo: **S1**. Decisioni ancora pendenti: richiesta UMLS (in parallelo), scelta modello LLM (in S1, dopo stima costo). Dettaglio in `ActualStatus.md`.

---

## S1 — Grafo + Closed Discovery

**Obiettivo:** costruire il grafo multi-ontologia e verificare che il sistema ritrovi i B già noti.

- [ ] **Definizione operativa di `first_year`** (nodo/arco): scelta della data (PubDate del fascicolo vs `pdat` E-utilities vs earliest). Emerso in S0: le due date divergono ai bordi (2026 gonfiato dagli "ahead-of-print", 2000 assottigliato). Decisione che condiziona la maschera del time-slicing.
- [ ] `ingest/pubtator_client.py`: entità normalizzate + relazioni PubTator3 (cacheate)
- [ ] Nodi MeSH per i concetti non coperti (Treg, permeabilità intestinale, ...)
- [ ] `graph/`: costruzione `MultiDiGraph`, nodi tipizzati, edges pesati con PMID + `first_year`
- [x] `RelationSource` (interfaccia) + implementazione LLM grounded (Gemini) — 2026-07-21. (Fallback co-occorrenza già in `graph/build_graph.py`; PubTator3 rimandato.)
- [x] **Stima di costo LLM su 100 abstract** → 910 tok/abstract, $0 free tier; modello scelto: Gemini 3.1 Flash Lite — 2026-07-21
- [~] Estrazione LLM grounded delle relazioni (con guardrail anti-contaminazione), cacheata — runner pronto e **avviato** (pre-cutoff ≤2021, riprendibile); in corso
- [x] `discovery/closed_discovery.py`: dati A e C, ritrova i B — 2026-07-20
- [x] Test: closed discovery ritrova ≥ 5 dei 7 B noti (**5/7 PASS**) — 2026-07-20

**Prossimo sprint (post-estrazione):** normalizzazione entità estratte → nodi grafo; grafo relazionale (`MultiDiGraph`); **ri-esecuzione S2** col nuovo layer per vedere se batte la frequenza.

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
