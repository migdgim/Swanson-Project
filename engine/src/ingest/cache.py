"""Cache Tier-1 su SQLite locale per il motore Swanson LBD.

Persiste in locale la risposta *grezza* di ogni sorgente esterna (PubMed,
PubTator3, relazioni, estrazioni LLM) e il registro delle run. Scopo: determinismo
e re-run offline — una seconda esecuzione non ri-scarica nulla e dà lo stesso
risultato (vedi `DesignArchitecture.md` §6.1 e §12).

Solo standard library (`sqlite3`): nessuna dipendenza esterna, così questo modulo
e i suoi test girano senza installare nulla.

Lo schema è quello fissato in DesignArchitecture §6.1:
  - papers(pmid PK, pub_date, journal, title, abstract, raw_json, fetched_at)
  - pubtator_annotations(pmid, entity_id, entity_type, mention, offset, raw_json)
  - relations_raw(source, subj_id, predicate, obj_id, pmid, raw_json)
  - llm_extractions(pmid, model, prompt_hash PK, response_json, created_at)
  - pipeline_runs(run_id PK, git_sha, config_snapshot_json, split, graph_max_date, created_at)

Il file DB vive in `engine/data/` ed è gitignored. Il percorso NON va hardcoded nel
codice applicativo: passarlo dalla config. `DEFAULT_DB_PATH` è solo un default comodo.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

DEFAULT_DB_PATH = Path("engine/data/cache.sqlite3")

# Versione dello schema Tier-1, scritta in `PRAGMA user_version`. Bump ad ogni
# modifica incompatibile dello schema, così un DB vecchio è riconoscibile.
SCHEMA_VERSION = 1

# Sorgenti ammesse per `relations_raw.source` (DesignArchitecture §6.1).
RELATION_SOURCES = frozenset({"semmeddb", "pubtator3", "cooccur", "llm"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    pmid       TEXT PRIMARY KEY,
    pub_date   TEXT,
    journal    TEXT,
    title      TEXT,
    abstract   TEXT,
    raw_json   TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pubtator_annotations (
    pmid        TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    entity_type TEXT,
    mention     TEXT,
    "offset"    INTEGER,
    raw_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_annot_pmid   ON pubtator_annotations(pmid);
CREATE INDEX IF NOT EXISTS idx_annot_entity ON pubtator_annotations(entity_id);

CREATE TABLE IF NOT EXISTS relations_raw (
    source    TEXT NOT NULL,
    subj_id   TEXT NOT NULL,
    predicate TEXT,
    obj_id    TEXT NOT NULL,
    pmid      TEXT,
    raw_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_pmid ON relations_raw(pmid);
CREATE INDEX IF NOT EXISTS idx_rel_subj ON relations_raw(subj_id);
CREATE INDEX IF NOT EXISTS idx_rel_obj  ON relations_raw(obj_id);

CREATE TABLE IF NOT EXISTS llm_extractions (
    pmid          TEXT NOT NULL,
    model         TEXT NOT NULL,
    prompt_hash   TEXT PRIMARY KEY,
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
"""


def _utcnow_iso() -> str:
    """Timestamp UTC ISO-8601 (provenienza, non entra nel calcolo riproducibile)."""
    return datetime.now(timezone.utc).isoformat()


def _dumps(obj: Any) -> str:
    """Serializzazione JSON deterministica (chiavi ordinate) per stabilità dei diff."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


class Cache:
    """Wrapper attorno a una connessione SQLite con lo schema Tier-1.

    Uso tipico::

        with Cache(cfg.db_path) as cache:
            if not cache.has_paper(pmid):
                cache.upsert_paper(pmid, ...)

    Idempotenza: `upsert_paper` è last-write-wins per PMID; `set_annotations` e
    `set_relations` sostituiscono il set esistente per (pmid[/source]), così un
    re-ingest non duplica righe.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        # WAL: letture concorrenti mentre si scrive; adatto a un DB locale.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    # -- ciclo di vita -----------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    # -- papers ------------------------------------------------------------

    def upsert_paper(
        self,
        pmid: str,
        *,
        pub_date: str | None,
        journal: str | None,
        title: str | None,
        abstract: str | None,
        raw: Mapping[str, Any],
        fetched_at: str | None = None,
    ) -> None:
        """Inserisce/aggiorna un paper. `pub_date` deve iniziare con l'anno a 4 cifre
        (YYYY o YYYY-MM-DD): è il contratto su cui si basa `year_counts()`."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO papers (pmid, pub_date, journal, title, abstract, raw_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pmid) DO UPDATE SET
                    pub_date   = excluded.pub_date,
                    journal    = excluded.journal,
                    title      = excluded.title,
                    abstract   = excluded.abstract,
                    raw_json   = excluded.raw_json,
                    fetched_at = excluded.fetched_at
                """,
                (pmid, pub_date, journal, title, abstract, _dumps(raw), fetched_at or _utcnow_iso()),
            )

    def has_paper(self, pmid: str) -> bool:
        """True se il PMID è già in cache (per saltare il download nel re-run offline)."""
        row = self._conn.execute("SELECT 1 FROM papers WHERE pmid = ?", (pmid,)).fetchone()
        return row is not None

    def get_paper(self, pmid: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM papers WHERE pmid = ?", (pmid,)).fetchone()

    def count_papers(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        return int(row[0])

    def iter_pmids(self) -> Iterator[str]:
        for row in self._conn.execute("SELECT pmid FROM papers ORDER BY pmid"):
            yield str(row["pmid"])

    def year_counts(self) -> dict[int, int]:
        """Conteggio dei paper per anno di pubblicazione — l'ispezione di sanità di S0.

        Legge l'anno dai primi 4 caratteri di `pub_date`; le righe con anno non
        numerico vengono ignorate (e sono osservabili come differenza con
        `count_papers()`)."""
        counts: dict[int, int] = {}
        cur = self._conn.execute(
            "SELECT substr(pub_date, 1, 4) AS y, COUNT(*) AS n "
            "FROM papers WHERE pub_date IS NOT NULL GROUP BY y"
        )
        for row in cur:
            y = row["y"]
            if isinstance(y, str) and y.isdigit() and len(y) == 4:
                counts[int(y)] = int(row["n"])
        return dict(sorted(counts.items()))

    # -- annotazioni PubTator3 --------------------------------------------

    def set_annotations(self, pmid: str, annotations: Sequence[Mapping[str, Any]]) -> None:
        """Sostituisce tutte le annotazioni del PMID (idempotente sul re-ingest).

        Ogni annotazione è un mapping con almeno `entity_id`; le chiavi note
        (`entity_type`, `mention`, `offset`) vanno nelle colonne dedicate, l'intero
        mapping è conservato in `raw_json`."""
        rows = [
            (
                pmid,
                str(a["entity_id"]),
                a.get("entity_type"),
                a.get("mention"),
                a.get("offset"),
                _dumps(a),
            )
            for a in annotations
        ]
        with self._conn:
            self._conn.execute("DELETE FROM pubtator_annotations WHERE pmid = ?", (pmid,))
            self._conn.executemany(
                'INSERT INTO pubtator_annotations '
                '(pmid, entity_id, entity_type, mention, "offset", raw_json) '
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def get_annotations(self, pmid: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute("SELECT * FROM pubtator_annotations WHERE pmid = ?", (pmid,))
        )

    # -- relazioni grezze --------------------------------------------------

    def set_relations(
        self, source: str, pmid: str, relations: Sequence[Mapping[str, Any]]
    ) -> None:
        """Sostituisce le relazioni di una (source, pmid) — idempotente sul re-ingest.

        `source` deve essere in RELATION_SOURCES. Ogni relazione ha `subj_id` e
        `obj_id`; `predicate` è opzionale."""
        if source not in RELATION_SOURCES:
            raise ValueError(f"source non valida: {source!r} (attese: {sorted(RELATION_SOURCES)})")
        rows = [
            (
                source,
                str(r["subj_id"]),
                r.get("predicate"),
                str(r["obj_id"]),
                pmid,
                _dumps(r),
            )
            for r in relations
        ]
        with self._conn:
            self._conn.execute(
                "DELETE FROM relations_raw WHERE source = ? AND pmid = ?", (source, pmid)
            )
            self._conn.executemany(
                "INSERT INTO relations_raw (source, subj_id, predicate, obj_id, pmid, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def get_relations(
        self, *, pmid: str | None = None, source: str | None = None
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        params: list[str] = []
        if pmid is not None:
            clauses.append("pmid = ?")
            params.append(pmid)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return list(self._conn.execute("SELECT * FROM relations_raw" + where, params))

    # -- estrazioni LLM (cache sul prompt) --------------------------------

    def get_llm_extraction(self, prompt_hash: str) -> sqlite3.Row | None:
        """Ritorna l'estrazione cacheata per quel prompt, o None (cache-miss)."""
        return self._conn.execute(
            "SELECT * FROM llm_extractions WHERE prompt_hash = ?", (prompt_hash,)
        ).fetchone()

    def upsert_llm_extraction(
        self,
        *,
        pmid: str,
        model: str,
        prompt_hash: str,
        response: Mapping[str, Any],
        created_at: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO llm_extractions (pmid, model, prompt_hash, response_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(prompt_hash) DO UPDATE SET
                    pmid          = excluded.pmid,
                    model         = excluded.model,
                    response_json = excluded.response_json,
                    created_at    = excluded.created_at
                """,
                (pmid, model, prompt_hash, _dumps(response), created_at or _utcnow_iso()),
            )

    # -- registro delle run (provenienza) ---------------------------------

    def start_run(
        self,
        run_id: str,
        *,
        git_sha: str | None,
        config_snapshot: Mapping[str, Any],
        split: str | None,
        graph_max_date: str | None,
        created_at: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO pipeline_runs "
                "(run_id, git_sha, config_snapshot_json, split, graph_max_date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    git_sha,
                    _dumps(config_snapshot),
                    split,
                    graph_max_date,
                    created_at or _utcnow_iso(),
                ),
            )

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
