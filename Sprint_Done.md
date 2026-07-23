# Sprint — Done (Swanson Project)

> Storico degli sprint completati e validati dal committente. Aggiornato a chiusura di ogni sprint.
> Serve a ridurre i token per sessione: qui il "già fatto", in `Sprint.md` il "da fare".

---

## S0 — Fondazioni ✅ (validato 2026-07-20)

**Obiettivo:** scaricare, normalizzare e cacheare il corpus pilota, in modo riproducibile.

- [x] `git init`, struttura monorepo (`engine/`, `web/`, `supabase/`), `.gitignore`, `.env.example` (2026-07-13)
- [x] Documentazione allineata (AGENTS, Project, DesignArchitecture, Sprint, ActualStatus) (2026-07-13)
- [x] `engine/config/pilot.yaml` (query MeSH A/C, B noti, finestre DEV/TEST, parametri) (2026-07-13; rifinito 2026-07-20 con sampling per-anno)
- [x] `pyproject.toml` → venv + install dipendenze runtime (2026-07-20)
- [x] Client E-utilities (`ingest/entrez_client.py`): key/mail da env, rate limiting 10 req/s, retry con backoff sui soli errori transitori (2026-07-20)
- [x] Cache SQLite (`ingest/cache.py`): schema Tier-1 + `eutils_cache` per re-run offline; ogni risposta grezza persistita (2026-07-20)
- [x] Rifinitura ingest + download del corpus A↔C: campionamento **per anno** (cap 80/anno per corridoio) per coprire le finestre DEV/TEST (2026-07-20)
- [x] Ispezione: conteggi per anno + sanity check (`ingest/download_corpus.py`) (2026-07-20)

**Numeri del corpus (eseguiti, non simulati):**
- **4061 paper** in cache; **3528 con abstract** (86.9%); copertura **1990–2026**, nessun paper senza anno.
- Corridoio A (disbiosi/microbioma): 1113 PMID · Corridoio C (neoplasie/carcinogenesi): 2960 PMID · A∩C (co-occorrenza): 12.
- Time-slicing — DEV grafo (≤2010): 1488 · DEV eval (2011–2015): 479 · TEST grafo (≤2015): 1967 · TEST eval (2016–2025): 1628.
- Idempotente e offline-riproducibile (re-run = 0 download). Verifiche: `ruff` pulito, `mypy --strict` (11 file), 8 test di parsing verdi.

**Caveat riportati (da affrontare in S1, non bug):**
1. `first_year`: la PubDate del fascicolo diverge dall'asse di ricerca `pdat` → 2026 gonfiato (ahead-of-print), 2000 assottigliato. La definizione operativa è un task di S1.
2. Il corpus è un **campione per-anno**, non esaustivo: C satura il cap in tutti i 37 anni, A in 13.

**Costo:** zero (NCBI E-utilities gratuito con API key; nessun servizio a pagamento in S0).

---

## S1-rel / S3-prep — Layer relazionale LLM grounded ✅ (2026-07-21)

**Obiettivo:** introdurre l'estrazione di relazioni *grounded* dagli abstract dietro
`RelationSource`, con guardrail anti-contaminazione, e stimarne costo/fattibilità prima di
estendere al corpus (leva per battere il baseline a frequenza, S2 = FAIL).

- [x] Ripristino ambiente locale (Mac): Homebrew + Python 3.12, venv, dipendenze runtime; stato riprodotto (S1 **5/7 PASS**, S2 **FAIL** PMI 0.100 vs freq 0.800). Cache 4061 paper rigenerata sul disco.
- [x] Dipendenza `google-generativeai` (approvata dal committente; nota: deprecata a favore di `google-genai`).
- [x] `relations/base.py`: tipi `Relation`/`Usage`/`ExtractionResult` + Protocol `RelationSource` (contratto `DesignArchitecture.md §7`).
- [x] `relations/prompt.py`: prompt di estrazione **grounded** versionato (`v1`); guardrail esplicito — mai giudizio di plausibilità/novità.
- [x] `relations/gemini_source.py`: `GeminiRelationSource` — temp 0, cache su disco (`llm_extractions`, chiave su prompt+modello), rate limiting, token misurati dall'API.
- [x] `relations/estimate_cost.py`: stima su **100 abstract** reali.
- [x] `relations/extract_corpus.py`: estrattore **riprendibile** (cache-first, stop pulito su quota); scope default = pre-cutoff ≤2021.
- [x] `ingest/cache.py`: metodi `sample_abstracts`, `get_paper_text`, `get/put_llm_extraction`.
- [x] Limiti free-tier **verificati** in dashboard e messi nel config (no placeholder).

**Numeri della stima (eseguiti, non simulati) — modello `gemini-flash-lite-latest` (= Gemini 3.1 Flash Lite), temp 0:**
- 100/100 estrazioni, 0 errori; **410 relazioni** (97/100 abstract con ≥1); 2 parse falliti (2%).
- Token misurati: **537 in / 374 out / 910 tot per abstract**.
- Estrapolazione corpus pre-cutoff (2397 paper ≤2021): ~1,3M in + ~0,9M out token.
- **Costo: $0** (free tier). Riferimento a pagamento ~$0,72 (listino DA VERIFICARE).
- Limiti free reali: **RPM 15 · TPM 250K · RPD 500** → estrazione pre-cutoff ~5 giorni a scatti, riprendibile.

**Guardrail rispettato:** l'LLM estrae solo triple presenti nel testo, con frase di evidenza verbatim; nessun giudizio A–B–C. Verificato a campione.

**Verifiche backend verdi:** `ruff` pulito, `mypy --strict` (26 file), 18 test.

**NON fatto (prossimo sprint):** normalizzazione entità estratte → nodi grafo; ricostruzione grafo relazionale; **ri-esecuzione S2** col nuovo layer.

---

## S2-rerun / S3 — Grafo relazionale + ri-esecuzione + open discovery ✅ (2026-07-23) — **PILOTA CHIUSO**

**Obiettivo:** completare l'estrazione, costruire il grafo relazionale grounded, ri-eseguire
S2 e verificare se il layer LLM batte finalmente la frequenza. Verdetto onesto atteso.

**Estrazione completata (eseguita, non simulata):**
- Modello **pinnato** `gemini-3.1-flash-lite` (`3.1-flash-lite-05-2026`). L'alias `-latest` era driftato 3.1→3.5 tra il 21 e il 23/07 → pin per coerenza del corpus multi-giorno. Le 991 estrazioni del 21/07 (3.1, provate identiche al pin) rietichettate in cache (backup `cache.sqlite.bak-prepin`).
- Billing Google attivato dal committente (€10) → rimosso il collo di bottiglia RPD. Client throttle alzato a 60 rpm (paid).
- **Copertura piena: 2397/2397 paper pre-cutoff (≤2021), 0 errori.** **8.920 relazioni** in cache (`llm_extractions`), 2373/2397 paper con ≥1 relazione. Costo effettivo: pochi centesimi.

**Codice (nuovo/modificato):**
- `graph/build_graph.py`: modalità **grounded** — arco A-B/B-C solo se B è descrittore *relazionalmente supportato* (via `relations/normalize.supported_descriptors`), stesso spazio nodi.
- `validation/run_time_slicing.py`: flag `--relations {cooccur,grounded}`; grounded = segnale di ranking sui candidati di co-occorrenza (non filtro), ground-truth invariata.
- `validation/time_slicing.py`: `OpenSlice` + `build_open_slices` + `evaluate_open_split`.
- `validation/run_open_discovery.py`: runner **open discovery time-sliced** (candidato = mezzo-ponte; hit = chiusura del lato mancante post-cutoff). Task e verdetto **pre-registrati**.

**Verdetti (eseguiti, TEST una volta sola, matching plain uniforme = niente p-hacking):**
1. **Closed S2, grafo co-occorrenza** (baseline): FAIL — P@10 PMI 0.100 vs freq **0.800**.
2. **Closed S2, grounding come segnale**: FAIL — grounded 0.000 vs freq **0.800**. Ground-truth ricca (86 hit). La frequenza domina *per tautologia* (hit N≥1 = persistenza dei frequenti).
3. **Open discovery** (anti-tautologia): FAIL ma informativo — grounded **0.200** vs freq **0.300** vs random 0.000. Il reframe **abbatte la tautologia** (freq 0.800→0.300); il grounded mostra segnale **non casuale** ma **non superiore** alla frequenza. Verdetto **sotto-potenziato** (29-38 hit, P@10 ±0.1).

**Conclusione onesta del pilota:** su questo corpus (campione 4061 paper) il layer relazionale LLM **non batte la frequenza** in modo dimostrabile. Il segnale grounded esiste ed è non-casuale; i suoi top candidati (Prebiotics, Bifidobacterium, Melanoma…) sono biologicamente sensati (osservazione, non metrica — guardrail rispettato). I limiti sono **noti e fixabili**: potenza statistica (più corpus) e copertura del matching menzione→MeSH (sinonimi uniformi / PubTator3). **Pilota chiuso qui per decisione del committente.**

**Verifiche backend verdi:** `ruff` pulito, `mypy --strict` (7 file toccati), **21 test**.

---

*Sprint successivi da fare: vedi `Sprint.md`.*
