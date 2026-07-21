"""Cache SQLite locale (Tier-1) per l'ingest.

Ogni risposta esterna (E-utilities, in seguito PubTator3/LLM) viene persistita qui
grezza, così una seconda esecuzione non ri-scarica nulla ed è deterministica/offline.
Il file vive in `engine/data/` ed è gitignored (vedi DesignArchitecture.md §6.1).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Schema Tier-1. Rispecchia DesignArchitecture.md §6.1 (le tabelle a valle
# di `papers` restano vuote in S0: si popolano da S1 in poi).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    pmid       TEXT PRIMARY KEY,
    pub_date   TEXT,
    pub_year   INTEGER,
    journal    TEXT,
    title      TEXT,
    abstract   TEXT,
    raw_json   TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_papers_year ON papers (pub_year);

CREATE TABLE IF NOT EXISTS pubtator_annotations (
    pmid        TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    entity_type TEXT,
    mention     TEXT,
    "offset"    INTEGER,
    raw_json    TEXT
);

CREATE TABLE IF NOT EXISTS relations_raw (
    source    TEXT NOT NULL,     -- semmeddb | pubtator3 | cooccur | llm
    subj_id   TEXT NOT NULL,
    predicate TEXT,
    obj_id    TEXT NOT NULL,
    pmid      TEXT,
    raw_json  TEXT
);

CREATE TABLE IF NOT EXISTS llm_extractions (
    pmid          TEXT NOT NULL,
    model         TEXT NOT NULL,
    prompt_hash   TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id               TEXT PRIMARY KEY,
    git_sha              TEXT,
    config_snapshot_json TEXT,
    split                TEXT,
    graph_max_date       TEXT,
    created_at           TEXT NOT NULL
);

-- Cache grezza delle chiamate E-utilities (esearch/efetch): garantisce il re-run offline.
CREATE TABLE IF NOT EXISTS eutils_cache (
    cache_key    TEXT PRIMARY KEY,
    endpoint     TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_raw TEXT NOT NULL,
    fetched_at   TEXT NOT NULL
);

-- Appartenenza di ogni paper ai corridoi (A/C): provenienza dell'esearch, base per
-- l'ancoraggio A-B-C della closed discovery e per il time-slicing.
CREATE TABLE IF NOT EXISTS paper_corridor (
    pmid     TEXT NOT NULL,
    corridor TEXT NOT NULL,        -- 'A' | 'C'
    PRIMARY KEY (pmid, corridor)
);

-- Sinonimi/entry-terms MeSH per descrittore (da db=mesh, cacheati): servono a mappare
-- le menzioni abbreviate estratte dall'LLM (es. "TNF-alpha") al descrittore ("Tumor
-- Necrosis Factor-alpha"), preservando lo spazio nodi MeSH nel confronto S2.
CREATE TABLE IF NOT EXISTS mesh_synonyms (
    descriptor    TEXT PRIMARY KEY,
    synonyms_json TEXT NOT NULL,     -- list[str], include il descrittore stesso
    fetched_at    TEXT NOT NULL
);
"""


class Cache:
    """Wrapper sottile su SQLite. Nessuna logica di dominio: solo persistenza grezza."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # --- eutils_cache ---------------------------------------------------

    def get_eutils(self, cache_key: str) -> str | None:
        row = self._conn.execute(
            "SELECT response_raw FROM eutils_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        return None if row is None else str(row["response_raw"])

    def put_eutils(
        self,
        cache_key: str,
        endpoint: str,
        request: dict[str, Any],
        response_raw: str,
        fetched_at: str,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO eutils_cache "
                "(cache_key, endpoint, request_json, response_raw, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (cache_key, endpoint, json.dumps(request, sort_keys=True), response_raw, fetched_at),
            )

    # --- papers ---------------------------------------------------------

    def has_paper(self, pmid: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM papers WHERE pmid = ?", (pmid,)).fetchone()
        return row is not None

    def known_pmids(self, pmids: list[str]) -> set[str]:
        """Sottoinsieme di `pmids` già presente in cache (per non ri-scaricare)."""
        known: set[str] = set()
        for i in range(0, len(pmids), 500):
            chunk = pmids[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT pmid FROM papers WHERE pmid IN ({placeholders})", chunk
            ).fetchall()
            known.update(str(r["pmid"]) for r in rows)
        return known

    def upsert_paper(
        self,
        *,
        pmid: str,
        pub_date: str | None,
        pub_year: int | None,
        journal: str | None,
        title: str | None,
        abstract: str | None,
        raw: dict[str, Any],
        fetched_at: str,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO papers "
                "(pmid, pub_date, pub_year, journal, title, abstract, raw_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pmid,
                    pub_date,
                    pub_year,
                    journal,
                    title,
                    abstract,
                    json.dumps(raw, ensure_ascii=False),
                    fetched_at,
                ),
            )

    def upsert_papers(self, papers: list[dict[str, Any]]) -> None:
        """Batch upsert; ogni dict ha le stesse chiavi di `upsert_paper`."""
        with self._tx() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO papers "
                "(pmid, pub_date, pub_year, journal, title, abstract, raw_json, fetched_at) "
                "VALUES (:pmid, :pub_date, :pub_year, :journal, :title, :abstract, :raw_json, :fetched_at)",
                [
                    {
                        "pmid": p["pmid"],
                        "pub_date": p["pub_date"],
                        "pub_year": p["pub_year"],
                        "journal": p["journal"],
                        "title": p["title"],
                        "abstract": p["abstract"],
                        "raw_json": json.dumps(p["raw"], ensure_ascii=False),
                        "fetched_at": p["fetched_at"],
                    }
                    for p in papers
                ],
            )

    # --- report ---------------------------------------------------------

    def count_papers(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()
        return int(row["n"])

    def count_with_abstract(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE abstract IS NOT NULL AND abstract != ''"
        ).fetchone()
        return int(row["n"])

    def counts_by_year(self) -> list[tuple[int | None, int]]:
        rows = self._conn.execute(
            "SELECT pub_year, COUNT(*) AS n FROM papers GROUP BY pub_year ORDER BY pub_year"
        ).fetchall()
        return [(r["pub_year"], int(r["n"])) for r in rows]

    def count_papers_max_year(self, year: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM papers WHERE pub_year IS NOT NULL AND pub_year <= ?",
            (year,),
        ).fetchone()
        return int(row["n"])

    def count_papers_between(self, lo: int, hi: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM papers "
            "WHERE pub_year IS NOT NULL AND pub_year >= ? AND pub_year <= ?",
            (lo, hi),
        ).fetchone()
        return int(row["n"])

    # --- paper_corridor -------------------------------------------------

    def set_corridor(self, corridor: str, pmids: list[str]) -> None:
        with self._tx() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO paper_corridor (pmid, corridor) VALUES (?, ?)",
                [(p, corridor) for p in pmids],
            )

    def pmids_in_corridor(self, corridor: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT pmid FROM paper_corridor WHERE corridor = ?", (corridor,)
        ).fetchall()
        return {str(r["pmid"]) for r in rows}

    def count_corridor_max_year(self, corridor: str, year: int) -> int:
        """Paper del corridoio con anno <= year (dimensione pre-cutoff per il time-slicing)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM paper_corridor pc JOIN papers p ON p.pmid = pc.pmid "
            "WHERE pc.corridor = ? AND p.pub_year IS NOT NULL AND p.pub_year <= ?",
            (corridor, year),
        ).fetchone()
        return int(row["n"])

    # --- abstracts (per estrazione relazioni) ---------------------------

    def get_paper_text(self, pmid: str) -> tuple[str | None, str | None] | None:
        """(title, abstract) del paper, o None se assente."""
        row = self._conn.execute(
            "SELECT title, abstract FROM papers WHERE pmid = ?", (pmid,)
        ).fetchone()
        if row is None:
            return None
        return (row["title"], row["abstract"])

    def sample_abstracts(self, *, limit: int) -> list[tuple[str, str | None, str]]:
        """Campione deterministico di (pmid, title, abstract) con abstract non vuoto.

        Ordinato per pmid: riproducibile e indipendente dall'ordine di inserimento.
        """
        rows = self._conn.execute(
            "SELECT pmid, title, abstract FROM papers "
            "WHERE abstract IS NOT NULL AND abstract != '' ORDER BY pmid LIMIT ?",
            (limit,),
        ).fetchall()
        return [(str(r["pmid"]), r["title"], str(r["abstract"])) for r in rows]

    # --- llm_extractions (cache estrazioni LLM) -------------------------

    def get_llm_extraction(self, *, prompt_hash: str, model: str) -> str | None:
        """Risposta LLM cacheata per (prompt_hash, model), o None. Re-run offline."""
        row = self._conn.execute(
            "SELECT response_json FROM llm_extractions WHERE prompt_hash = ? AND model = ?",
            (prompt_hash, model),
        ).fetchone()
        return None if row is None else str(row["response_json"])

    def put_llm_extraction(
        self,
        *,
        pmid: str,
        model: str,
        prompt_hash: str,
        response_json: str,
        created_at: str,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO llm_extractions "
                "(pmid, model, prompt_hash, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (pmid, model, prompt_hash, response_json, created_at),
            )

    def iter_llm_extractions(self, model: str) -> list[tuple[str, str]]:
        """(pmid, response_json) di tutte le estrazioni per un modello."""
        rows = self._conn.execute(
            "SELECT pmid, response_json FROM llm_extractions WHERE model = ? ORDER BY pmid",
            (model,),
        ).fetchall()
        return [(str(r["pmid"]), str(r["response_json"])) for r in rows]

    def get_raw_article(self, pmid: str) -> str | None:
        """`raw_json` grezzo del paper (per estrarne i descrittori MeSH), o None."""
        row = self._conn.execute(
            "SELECT raw_json FROM papers WHERE pmid = ?", (pmid,)
        ).fetchone()
        return None if row is None else str(row["raw_json"])

    def count_llm_extractions(self, model: str | None = None) -> int:
        if model is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM llm_extractions"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM llm_extractions WHERE model = ?", (model,)
            ).fetchone()
        return int(row["n"])

    # --- mesh_synonyms --------------------------------------------------

    def get_mesh_synonyms(self, descriptor: str) -> list[str] | None:
        row = self._conn.execute(
            "SELECT synonyms_json FROM mesh_synonyms WHERE descriptor = ?", (descriptor,)
        ).fetchone()
        if row is None:
            return None
        val = json.loads(row["synonyms_json"])
        return [str(x) for x in val] if isinstance(val, list) else None

    def put_mesh_synonyms(self, descriptor: str, synonyms: list[str], fetched_at: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mesh_synonyms (descriptor, synonyms_json, fetched_at) "
                "VALUES (?, ?, ?)",
                (descriptor, json.dumps(synonyms, ensure_ascii=False), fetched_at),
            )

    # --- pipeline_runs --------------------------------------------------

    def record_run(
        self,
        *,
        run_id: str,
        git_sha: str | None,
        config_snapshot: dict[str, Any],
        split: str | None,
        graph_max_date: str | None,
        created_at: str,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pipeline_runs "
                "(run_id, git_sha, config_snapshot_json, split, graph_max_date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    git_sha,
                    json.dumps(config_snapshot, ensure_ascii=False, sort_keys=True),
                    split,
                    graph_max_date,
                    created_at,
                ),
            )
