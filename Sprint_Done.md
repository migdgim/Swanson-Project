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

*Sprint successivi da fare: vedi `Sprint.md`.*
