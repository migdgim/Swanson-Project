# Swanson Project — Design & Architecture

> Documento di riferimento sull'architettura tecnica del motore di Literature-Based Discovery.
> Caricamento: su richiesta (decisioni architetturali, nuovo componente, refactor).
> Ultimo aggiornamento: 2026-07-13.

---

## 1. Visione tecnica in una riga

Un **motore LBD** che trasforma la letteratura biomedica (PubMed) in un **grafo di conoscenza multi-ontologia**, applica il **modello ABC di Swanson** per proporre collegamenti non ovvi, e — dato che il valore è nel filtro — **valida sé stesso con un test temporale** prima di pubblicare. Motore **local-first** in Python; risultati **curati** pubblicati su Postgres/Supabase con una web UI aperta ai ricercatori.

---

## 2. Principi architetturali

1. **Filter-first.** Il generatore di ipotesi è la parte facile; il filtro è il prodotto. Nessun componente entra in pipeline senza chiedersi se riduce o amplifica le correlazioni spurie.
2. **Separazione motore / pubblicazione.** Il *calcolo* (ingest, grafo, discovery, validazione) è locale, veloce, deterministico, offline-riproducibile. La *pubblicazione* è un passo distinto che spinge su Supabase **solo** lo snapshot curato e validato. Le due cose non si mescolano.
3. **Interfacce astratte sui punti di incertezza.** Le sorgenti che potrebbero cambiare (relazioni: SemMedDB vs fallback; entità; metriche di ranking) stanno dietro interfacce, così si sostituiscono senza rifattorizzare.
4. **Determinismo.** Seed fissi ovunque; ogni risposta esterna (PubMed, PubTator3, LLM) cacheata su disco; ogni run registra i propri parametri e la propria provenienza.
5. **Honest failure.** Nessun dato finto, nessuno stub, nessun numero non calcolato. Un blocco reale si segnala, non si aggira con placeholder.
6. **Anti-contaminazione temporale.** Nel time-slicing nulla che "conosca il futuro" può influenzare la generazione o il ranking — incluso l'LLM, confinato all'estrazione grounded.

---

## 3. Stack tecnologico

| Componente | Tech | Note |
|---|---|---|
| Linguaggio motore | **Python 3.11+**, tipizzato (mypy strict) | `engine/` |
| Ingest | **NCBI E-utilities** via `Biopython.Entrez` + API key | 10 req/s, rate-limited |
| Riconoscimento entità | **PubTator3 API** | ID normalizzati (Gene, Disease, Chemical, Species, Mutation, CellLine) + relazioni |
| Concetti extra | **MeSH** (pubblico dominio) | copre ciò che PubTator3 non tipizza (Treg, permeabilità intestinale, ...) |
| Relazioni | **SemMedDB** (UMLS) *oppure* fallback | dietro `RelationSource` (vedi §7) |
| Estrazione LLM (fallback) | **Anthropic Claude** (modello da S1) | solo estrazione grounded; output cacheato, versione pinnata |
| Grafo (calcolo) | **NetworkX** in-memory | nessun graph DB |
| Semantica | **SPECTER2** (embeddings paper) + **FAISS** locale | S3, dipendenze pesanti |
| Cache/lavoro | **SQLite** locale (`engine/data/`) | gitignored, riproducibilità offline |
| Dati pubblicati | **Supabase (Postgres)** | verità pubblica, solo subset curato — S4 |
| Web pubblica | **Next.js** + viz grafo (Cytoscape.js/Sigma.js) su **Vercel** | S5 |
| Lettura personale | **Obsidian** (Markdown export) | opzionale, subset curato |

**Perché queste scelte (razionale sintetico):**
- **NetworkX, non Neo4j.** Alla scala pilota (migliaia di nodi) NetworkX fa in memoria tutti gli algoritmi di grafo; Neo4j aggiungerebbe un secondo DB da ospitare/proteggere senza vantaggi. Se un giorno servissero query di grafo *nel* DB pubblico, Postgres ha l'estensione Apache AGE — ma non è previsto.
- **Postgres/Supabase per pubblicare, non per calcolare.** Dà API, auth e hosting pronti per la fruizione pubblica; il grafo vive come tabelle e si visualizza nel browser (JSON → Cytoscape/Sigma), senza bisogno di un graph DB dedicato.
- **PubTator3 + MeSH, non NER custom.** Entità già normalizzate a ID stabili risolvono il problema "stesso concetto, molti nomi". MeSH riempie i buchi ontologici di PubTator3.

---

## 4. Struttura del repository (monorepo)

```
engine/src/
  ingest/       # entrez_client, pubtator_client, mesh, cache SQLite
  graph/        # nodi tipizzati (multi-ontologia), edges pesati con provenienza
  discovery/    # closed_discovery, open_discovery, ranking dei B
  validation/   # time_slicing, baselines, metriche (precision@k, recall)
  export/        # markdown/obsidian del subset curato
  publish/      # client Supabase, mapping snapshot -> schema pubblico
engine/config/  # pilot.yaml (query MeSH, finestre, parametri) — mai hardcoded
engine/data/    # cache + artefatti (gitignored)
engine/tests/
web/            # Next.js (S5)
supabase/       # migrazioni schema pubblico (S4)
```

---

## 5. Flusso dati (pipeline)

```
PubMed (E-utilities)
   → PubTator3 + MeSH        [entità normalizzate, multi-ontologia]
   → RelationSource          [SemMedDB | co-occorrenza + PubTator3 rel + LLM grounded]
   → Grafo NetworkX          [nodi tipizzati, edges pesati con PMID + data]
   → Discovery ABC           [closed: A,C → B noti | open: A → C nuovi via B]
   → Filtro + Ranking        [specificità: TF-IDF, PMI, novità semantica]
   → Time-slicing            [DEV tara, TEST giudica una volta — baselines]
   → Snapshot curato         [publish → Supabase | export → Obsidian]
```

Ogni freccia legge/scrive dalla **cache SQLite**: una seconda esecuzione non ri-scarica nulla ed è deterministica.

---

## 6. Modello dei dati

### 6.1 Tier 1 — cache di lavoro (SQLite locale, gitignored)

Tabelle grezze, una per sorgente, con la risposta originale intatta (per riproducibilità e re-run offline):
- `papers(pmid PK, pub_date, journal, title, abstract, raw_json, fetched_at)`
- `pubtator_annotations(pmid, entity_id, entity_type, mention, offset, raw_json)`
- `relations_raw(source, subj_id, predicate, obj_id, pmid, raw_json)`  — `source ∈ {semmeddb, pubtator3, cooccur, llm}`
- `llm_extractions(pmid, model, prompt_hash, response_json, created_at)`  — cache LLM, chiave sul prompt
- `pipeline_runs(run_id PK, git_sha, config_snapshot_json, split, graph_max_date, created_at)`

### 6.2 Tier 2 — dati pubblicati (Supabase Postgres, S4)

Solo dati **derivati e curati**, su **identificatori aperti** (MeSH, NCBI Gene, tassonomia, PMID). Schizzo dello schema:

```sql
-- provenienza di ogni run pubblicata
create table pipeline_runs (
  run_id uuid primary key default gen_random_uuid(),
  git_sha text, corridor_id text, split text,        -- 'dev' | 'test'
  graph_max_date date, params jsonb, created_at timestamptz default now()
);

-- entità (nodi) su ID aperti
create table entities (
  entity_id text primary key,                         -- es. 'MESH:D064806', 'GENE:7124'
  ontology text not null,                             -- 'mesh' | 'ncbi_gene' | 'taxonomy'
  label text not null, entity_type text
);

-- relazioni (archi) con provenienza e peso
create table edges (
  run_id uuid references pipeline_runs, 
  subj_id text references entities, obj_id text references entities,
  predicate text, weight numeric, evidence_pmids int[],
  primary key (run_id, subj_id, obj_id, predicate)
);

-- ipotesi ABC curate (i B che collegano A e C)
create table hypotheses (
  hypothesis_id uuid primary key default gen_random_uuid(),
  run_id uuid references pipeline_runs,
  a_id text, b_id text, c_id text,
  score numeric, rank int, metric text, curated bool default false
);

-- metriche di validazione, in chiaro
create table validation_metrics (
  run_id uuid references pipeline_runs,
  metric text, k int, value numeric, baseline text  -- 'model' | 'frequency' | 'random'
);
```

**RLS:** lettura pubblica (`select` a `anon`) su tutte le tabelle pubblicate; scrittura solo `service_role` (dal passo `publish`). **Nessuna riga grezza SemMedDB/UMLS** finisce qui (vincoli di licenza — §11).

### 6.3 Il grafo in memoria

`networkx.MultiDiGraph`. Nodo = entità con attributi `{ontology, type, label, first_year}`. Arco = relazione con attributi `{predicate, source, weight, pmids, first_year}`. `first_year` sul nodo/arco è ciò che rende il time-slicing una semplice **maschera** sul grafo (filtro per data), non una ricostruzione.

---

## 7. Interfacce astratte chiave

Contratti di design (non implementazione). Il punto è poter sostituire la sorgente senza toccare il resto.

```python
class RelationSource(Protocol):
    """SemMedDB, oppure il fallback, dietro la stessa firma."""
    def relations_for(self, pmids: list[str]) -> Iterable[Relation]: ...

class EntitySource(Protocol):
    def entities_for(self, pmids: list[str]) -> Iterable[Entity]: ...

class RankingMetric(Protocol):
    """TF-IDF, PMI, novità semantica: confrontabili sul DEV set."""
    def score(self, b: NodeId, a: NodeId, c: NodeId, graph: Graph) -> float: ...
```

Il **fallback** di `RelationSource` combina: co-occorrenza MeSH pesata + relazioni PubTator3 + estrazione LLM grounded — tutte normalizzate nella stessa `Relation`. Quando arriva SemMedDB, si aggiunge un'implementazione e si cambia una riga di config.

---

## 8. Discovery ABC

- **Closed discovery** (S1): dati A e C noti, trova i B sul cammino A–B–C nel grafo. Test di sanità: ritrova i B *già noti* (config `known_b_terms`). Se ne ritrova < 5, la pipeline è rotta → stop.
- **Open discovery** (S3): dato A, trova C non ovvi tramite B intermedi, dove A e C **non** co-occorrono. È qui che nascono le ipotesi nuove — ma solo dopo che il time-slicing ha dato fiducia al filtro.

---

## 9. Validazione — il contratto (S2)

- **Maschera temporale:** grafo = sottografo con `first_year ≤ graph_max_date`. La separazione DEV/TEST è imposta dal codice (le finestre vengono dal config; il TEST è eseguibile una volta, con guardia esplicita sul "non ho guardato il TEST prima di congelare").
- **Ground truth (hit):** ≥ N predicazioni A–B *e* B–C nel corpus post-cutoff. N tarato su DEV.
- **Baselines:** frequenza pura + random. Il modello deve batterle o è dichiarato non funzionante.
- **Metriche:** precision@{10,25,50}, recall sulle relazioni note, lista esplicita dei falsi positivi top-10.
- **Output:** report con numeri reali (mai inventati) e verdetto binario pass/fail.

---

## 10. Ranking dei B

Filtro preliminare per document frequency (`df_min`, `df_max_ratio`: fuori i termini troppo rari e le stopword di dominio). Poi ≥ 2 metriche di specificità confrontate sul DEV set (TF-IDF/rarità inversa; PMI(B; A,C); in S3 novità semantica SPECTER2: un buon B collega cluster **lontani** nello spazio degli embeddings). Si sceglie la metrica vincente **coi numeri del DEV**, e la si documenta.

**A cosa servono SPECTER2 + FAISS (S3):** SPECTER2 mappa ogni paper in un vettore ("coordinata di significato") specifico per testi scientifici; FAISS indicizza e cerca i vicini in fretta. Servono a misurare la **distanza semantica** — un ponte tra aree lontane vale più di un vicino ovvio — segnale che il puro conteggio non cattura. Rimandati a S3 perché il verdetto di base (S1/S2) non ne ha bisogno e `torch` è pesante.

---

## 11. Pubblicazione, licenze, pubblico dominio

- **MeSH, NCBI Gene, tassonomia, PMID** sono aperti → costituiscono la superficie pubblica.
- **UMLS/SemMedDB** richiede licenza (gratuita, aperta anche a ricercatori indipendenti non-medici; approvazione in giorni). Alcuni vocabolari interni hanno vincoli di ridistribuzione: si **calcola** con SemMedDB in privato, si **pubblicano solo i risultati derivati** (i nostri ranking, con i PMID a supporto), mai le righe grezze.
- Il passo `publish` fa da guardia: mappa lo snapshot su ID aperti prima di scrivere su Supabase.

---

## 12. Riproducibilità e provenienza

Ogni run: `run_id` + `git_sha` + snapshot del config + finestra temporale, salvati in `pipeline_runs`. Seed fisso (`config.seed`). Cache su ogni chiamata esterna. Una run è ri-eseguibile offline e dà lo stesso risultato.

---

## 13. Segreti e sicurezza

`.env` (gitignored) per NCBI, Anthropic, UMLS, Supabase. In repo solo `.env.example`. Il passo `publish` usa `service_role` (mai esposto al frontend); la web UI usa la chiave `anon`/publishable in sola lettura sotto RLS.

---

## 14. Decisioni chiuse (registro)

| # | Decisione | Razionale |
|---|---|---|
| 1 | NetworkX in-memory per il calcolo | scala pilota; niente overhead graph DB |
| 2 | Supabase/Postgres per la pubblicazione, non Neo4j | API+auth+hosting pronti; viz nel browser |
| 3 | PubTator3 **+ MeSH** (multi-ontologia) | copre anche Treg, permeabilità intestinale, ... |
| 4 | SemMedDB con fallback dietro interfaccia | non blocca l'avvio; innesto successivo |
| 5 | LLM solo estrazione grounded | anti-contaminazione del time-slicing |
| 6 | SQLite cache locale + snapshot curato su Supabase | motore riproducibile, pubblico pulito da vincoli UMLS |
| 7 | Embeddings (SPECTER2/FAISS) rimandati a S3 | verdetto di base non li richiede; `torch` pesante |
