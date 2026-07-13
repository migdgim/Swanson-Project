# Swanson Project — istruzioni di progetto

> Motore di **Literature-Based Discovery (LBD)** in Python. Ricerca **non commerciale**, destinata al **pubblico dominio** (dati aperti + web pubblica per ricercatori). Caricato a ogni sessione.

## Cos'è

Estrae entità e relazioni dalla letteratura biomedica (PubMed), costruisce un grafo di conoscenza e genera **ipotesi di collegamenti non ovvi** secondo il modello **ABC di Swanson** (A e C non co-occorrono, ma un termine B li collega).
Dominio pilota: **disbiosi/microbioma (A) ↔ tumorigenesi e immunità antitumorale (C)**. Espandibile ad altri corridoi A→C.

## Principi non negoziabili

- **Il valore è nel FILTRO, non nella generazione.** Un grafo di co-occorrenze produce migliaia di correlazioni spurie; il sistema esiste per separare segnale da rumore. Ogni scelta va valutata così: *riduce l'apofenia o la amplifica?*
- **Il successo si misura col time-slicing**, non producendo connessioni. Separazione DEV/TEST rigorosa; baseline obbligatorie (frequenza + random). Se non batte il baseline a frequenza, il sistema **non funziona** e va detto.
- **Un fallimento riportato onestamente vale più di un successo simulato.** Mai stub, `TODO`, `pass  # later`, dati finti, numeri inventati. Ogni metrica proviene da codice **effettivamente eseguito**; se non hai eseguito, scrivi "non eseguito". Se un blocco è reale (es. licenza mancante), **fermati e segnalalo**.
- **Determinismo e riproducibilità.** Seed fissi ovunque; ogni risposta API/LLM cacheata su disco; le run devono essere ri-eseguibili offline.
- **Guardrail LLM anti-contaminazione.** L'LLM può SOLO estrarre relazioni presenti nel **testo dell'abstract**. MAI fargli giudicare la plausibilità di un legame A–B–C: contaminerebbe il time-slicing con conoscenza dal futuro.

## Stack (sintesi — dettaglio in `DesignArchitecture.md`)

- **Motore:** Python 3.11+, **NetworkX** in-memory, **SQLite** come cache grezza locale (in `.gitignore`).
- **Entità:** **PubTator3** (ID normalizzati) + **MeSH** (concetti pubblico dominio) → grafo multi-ontologia.
- **Relazioni:** **SemMedDB** (UMLS, quando disponibile) *oppure* fallback (co-occorrenza MeSH pesata + relazioni PubTator3 + estrazione LLM grounded) dietro **un'unica interfaccia astratta**.
- **Semantica (S3):** embeddings **SPECTER2** + **FAISS**.
- **Ingest:** NCBI **E-utilities** (`Biopython.Entrez`) + API key, rate-limited.
- **Layer pubblico:** **Supabase (Postgres)** = verità dei dati *pubblicati e curati* + web **Next.js** (viz grafo Cytoscape/Sigma) su Vercel. **NIENTE Neo4j.**
- **Layer personale:** export **Obsidian** (opzionale, solo subset curato).

## Regole operative

- **Lavora solo dentro la project root.** Non toccare `.env`, file di sistema, né i progetti `guestrace`/`firetrace` su Supabase.
- **Fai solo ciò che è richiesto.** Niente feature extra, astrazioni premature, refactor non richiesti, dashboard non richieste.
- **Nessuna dipendenza nuova senza chiedere.**
- **Config in `engine/config/`**, mai hardcoded (query MeSH, finestre temporali, parametri).
- Rispetta `token-optimization.md`.

## Divisione delle verifiche (direttiva committente)

L'assistente verifica **solo ciò che è testabile da backend**: SQL/migration/RLS (via MCP Supabase), `tsc --noEmit`, lint, `pytest`, e le metriche prodotte da codice effettivamente eseguito. **Non** tenta login o test della UI nel browser. La **verifica della UI la esegue il committente**: l'assistente prepara il codice, segnala cosa controllare, attende l'OK.

## Chiusura sprint

1 sprint = 1 sessione. A fine sprint: **fermati, riporta i numeri, aspetta l'OK** del committente prima del successivo e prima di commit/push. Poi sposta i task in `Sprint_Done.md` e aggiorna `ActualStatus.md`.

## Avvio sessione

Leggi **`ActualStatus.md`** + **`Sprint.md`** prima di ogni altra cosa. Non esplorare il codice finché non hai il contesto dai `.md`.
