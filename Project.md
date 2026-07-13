# Project — Literature-Based Discovery Engine (Swanson Project)

> Brief completo del progetto. Le decisioni di architettura sono chiuse (vedi `DesignArchitecture.md`); si rimettono in discussione solo per errori tecnici bloccanti.
> Ultimo aggiornamento: 2026-07-13.

---

## Contesto e motivazione

Costruire un motore di **Literature-Based Discovery (LBD)** in Python: un sistema che estrae entità e relazioni dalla letteratura biomedica su PubMed, costruisce un grafo di conoscenza e genera **ipotesi di relazioni non ovvie** secondo il modello **ABC di Swanson** — A e C non co-occorrono in letteratura, ma sono collegati da un termine intermedio B.

Dominio pilota: **disbiosi intestinale / microbioma (A) ↔ tumorigenesi e risposta immunitaria antitumorale (C)**. È un esempio-guida per validare la solidità dell'idea; l'architettura deve restare **espandibile e scalabile ad altri corridoi A→C**.

Progetto di ricerca **non commerciale**, con una motivazione personale e un fine più ampio: metterlo a **pubblico dominio** — dati aperti e interfaccia web consultabile — a disposizione di altri ricercatori.

Il paper fondativo di riferimento è **Swanson 1986** (Raynaud / olio di pesce).

---

## Obiettivo

Data una porzione di PubMed su un corridoio A→C, generare una lista **rankata e validata** di termini intermedi B che collegano A e C — dove il criterio di successo non è "produrre connessioni" ma **superare un test di validazione temporale predefinito**.

**Il perché, che vincola il design:** un grafo denso di co-occorrenze produce migliaia di correlazioni spurie. Il valore del sistema sta interamente nel **filtro**, non nella generazione. Ogni scelta implementativa va valutata contro questo: riduce l'apofenia o la amplifica?

---

## Il test che definisce il successo — Time-Slicing

È il cuore del progetto. Va implementato per primo come **contratto**, non come afterthought.

1. Grafo costruito **solo** su paper con data di pubblicazione ≤ 2015-12-31.
2. Il sistema genera i suoi top-N termini B candidati.
3. Si verifica quali candidati corrispondono a relazioni **effettivamente pubblicate e consolidate nel 2016–2025** — misurate contro il corpus post-2015 che il sistema non ha mai visto.
4. Il campo microbioma-cancro è esploso proprio in quegli anni: c'è segnale reale da recuperare. Se il sistema non ritrova ciò che è *già noto oggi ma ignoto nel 2015*, qualunque "correlazione inedita" successiva è rumore.

**Protezione contro l'overfitting — vincolo non negoziabile:**

| Split | Finestra | Uso |
|---|---|---|
| DEV | grafo ≤2010 → verifica su 2011–2015 | **Qui** e solo qui si tarano parametri, soglie, metriche |
| TEST | grafo ≤2015 → verifica su 2016–2025 | Si esegue **una volta sola**, a parametri congelati |

**MAI** tarare nulla guardando la finestra TEST. Se dopo aver visto il TEST vuoi modificare il ranking, hai bruciato il test: dichiaralo nel report e non spacciarlo come validazione.
Un **terzo asse** temporale (finestra intermedia di validazione, o valutazione a scorrimento) è previsto come opzione già predisposta nel config — attivabile senza rifare il codice. Per ora si resta su DEV/TEST (semplice prima, complicabile dopo).

**Definizione operativa dell'"hit" (da fissare su DEV, congelare per TEST):** un B è un hit se, nel corpus post-cutoff, esistono ≥ N paper che asseriscono *sia* A–B *sia* B–C come **predicazioni** (non semplice co-occorrenza), per non misurare solo la crescita del corpus. N tarato su DEV.

**Baseline obbligatoria:** il ranking va confrontato con (a) baseline a frequenza pura e (b) baseline random. Se non batte la frequenza, **il sistema non funziona** e va detto. Nessun risultato senza confronto coi baseline.

Metriche: precision@k (k = 10, 25, 50), recall sulle relazioni note post-2016, ed elenco **esplicito** dei falsi positivi ai primi 10 posti.

---

## Il ranking dei termini B — dove si vince o si perde

**NON ordinare per frequenza.** In questo dominio i termini frequenti sono rumore: `inflammation` è di fatto una stopword, comparirà in cima senza significare nulla.

Implementa e **confronta almeno due metriche di specificità**, poi scegli sul DEV set:
- pesatura tipo TF-IDF / rarità inversa del termine nel corpus di fondo,
- pointwise mutual information (PMI) tra B e i due poli A e C,
- novità semantica via embeddings (B che collega cluster distanti nello spazio SPECTER2 — S3).

Filtro preliminare per document frequency: scarta i termini troppo generici e quelli troppo rari (rumore da singolo paper). Documenta nel codice **perché** hai scelto la metrica vincente, coi numeri del DEV set. Se il risultato è ambiguo, dillo — non fabbricare una motivazione.

---

## Decisioni di architettura (chiuse — dettaglio in `DesignArchitecture.md`)

- **Ingest:** NCBI E-utilities via `Biopython.Entrez` con API key (10 req/s). **Non** MCP (è un layer conversazionale, inadatto a un ETL bulk).
- **Entità:** **PubTator3 API** (ID stabili: NCBI Gene, MeSH, tassonomia) **+ MeSH** per i concetti non coperti da PubTator3 (es. Treg, permeabilità intestinale) → **grafo multi-ontologia**. Nessun NER custom.
- **Relazioni:** **SemMedDB** (richiede licenza UMLS). Se non disponibile all'avvio, **fallback** dietro la stessa interfaccia astratta: co-occorrenza MeSH pesata + relazioni PubTator3 + estrazione LLM **grounded** sugli abstract. SemMedDB innestabile dopo senza rifattorizzare.
- **Guardrail LLM:** l'LLM estrae solo relazioni presenti nel testo; **mai** giudica la plausibilità di legami A–B–C (anti-contaminazione del time-slicing).
- **Grafo (calcolo):** **NetworkX in-memory**. Niente Neo4j/Docker: sotto ~100k nodi è overhead puro.
- **Semantica:** embeddings **SPECTER2** + **FAISS** locale (S3).
- **Cache/persistenza di lavoro:** **SQLite** locale. Ogni risposta API grezza va cacheata su disco: run riproducibili e ri-eseguibili offline.
- **Pubblicazione (novità):** il progetto è di pubblico dominio. La **verità dei dati pubblicati** è **Supabase (Postgres)**; il **motore** resta local-first e vi pubblica solo lo **snapshot curato e validato** (identificatori aperti: MeSH/Gene/tassonomia/PMID; nessuna riga grezza UMLS). Sopra, una **web UI pubblica** (Next.js, viz grafo Cytoscape/Sigma) su Vercel. **Niente Neo4j.**
- **Output personale:** export **Markdown** (frontmatter YAML + wikilink) verso Obsidian, **solo** per il subset finale curato — layer di lettura secondario, non il motore.

---

## Scope e struttura (monorepo)

```
engine/                  # motore Python
  src/
    ingest/              # E-utilities, PubTator3, caching su SQLite
    graph/               # costruzione grafo NetworkX, entità, edges (multi-ontologia)
    discovery/           # ABC: closed discovery, open discovery, ranking dei B
    validation/          # time-slicing, baselines, metriche
    export/              # generazione Markdown per Obsidian
    publish/             # push dello snapshot curato su Supabase
  tests/
  config/                # query MeSH, parametri, finestre temporali — mai hardcoded
  data/                  # cache API + artefatti (in .gitignore)
web/                     # interfaccia web pubblica (Next.js) — S5
supabase/                # schema e migrazioni del layer di pubblicazione — S4
```

**NON toccare:** `.env`, file fuori dalla project root, configurazioni di sistema, i progetti `guestrace`/`firetrace`.

---

## Sprint (esegui in ordine, non saltare — dettaglio in `Sprint.md`)

- **S0 — Fondazioni.** Setup, config, client E-utilities (API key + rate limiting), caching SQLite, query MeSH del corpus pilota (~3–5k abstract). Deliverable: corpus scaricato, cacheato, ispezionabile.
- **S1 — Grafo + Closed Discovery.** PubTator3 + MeSH → entità normalizzate → grafo NetworkX. Closed discovery ritrova i B già noti (butirrato/SCFA, LPS, TLR4, IL-6, TNF-α, Treg, permeabilità intestinale)? Se non ne ritrova ≥5, **fermati e riportamelo.** Include la **stima di costo LLM su 100 abstract** prima dell'estrazione completa.
- **S2 — Time-Slicing.** Protocollo DEV/TEST, baselines, metriche. Verdetto binario: la pipeline ha potere predittivo, oppure no.
- **S3 — Ranking avanzato + Open Discovery.** Solo se S2 passa. Embeddings SPECTER2 + FAISS, metriche di specificità, generazione dei B candidati nuovi.
- **S4 — Pubblicazione.** Provisioning Supabase, schema, publish dello snapshot curato, export Obsidian del subset.
- **S5 — Web UI pubblica.** Next.js su Vercel: esploratore grafo, pagine-ipotesi con evidenze, report di validazione trasparente.

Al termine di ogni sprint: **fermati, riporta i numeri, aspetta conferma** prima del successivo.

---

## Constraints

- Python 3.11+. Nessuna dipendenza nuova senza chiedere prima.
- Codice tipizzato, testabile, con test sui componenti di discovery e validation (sono il cuore: se sbagliano, tutto mente).
- Ogni chiamata API/LLM cacheata. Run deterministiche: seed fissi ovunque.
- Parametri e query in `config/`, mai hardcoded.
- **Fai solo ciò che è richiesto.** Niente feature extra, astrazioni premature, refactor non richiesti, dashboard non richieste.
- **Niente stub, `TODO`, `pass  # implement later`, funzioni che ritornano dati finti.** Se un componente non è implementabile per un blocco reale, **fermati e dillo** — non simulare con placeholder.
- **Niente numeri inventati.** Ogni metrica riportata proviene da codice eseguito. Se non hai eseguito, scrivi "non eseguito".

---

## Acceptance Criteria

- [ ] Corpus pilota scaricato e cacheato; re-run offline funzionante
- [ ] Grafo costruito da entità PubTator3 + MeSH normalizzate (non stringhe raw)
- [ ] Closed discovery ritrova ≥ 5 dei termini B noti
- [ ] Time-slicing con separazione DEV/TEST rigorosa e non aggirabile dal codice
- [ ] Ranking confrontato contro baseline-frequenza e baseline-random, con numeri
- [ ] Report finale con precision@k, falsi positivi in chiaro, verdetto esplicito pass/fail
- [ ] Snapshot curato pubblicato su Supabase su identificatori aperti
- [ ] Export Obsidian funzionante sul solo subset finale

---

## Stop Conditions — fermati e chiedi prima di

- Cambiare una decisione di architettura chiusa
- Aggiungere qualunque dipendenza
- Cancellare file
- Proseguire a uno sprint successivo senza conferma
- Proseguire se closed discovery (S1) fallisce
- Toccare qualunque cosa fuori dalla project root o i progetti Supabase esistenti

---

## Progress

Dopo ogni step completato, output in una riga: `✅ [cosa è stato fatto] — [file toccati]`.
Se qualcosa non funziona, dillo subito e con precisione. **Un fallimento riportato onestamente vale più di un successo simulato**: l'intero progetto esiste per distinguere segnale da rumore, e un agente che maschera i propri fallimenti rende il sistema inutile per costruzione.
