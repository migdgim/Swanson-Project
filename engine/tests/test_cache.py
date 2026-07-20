"""Test della cache Tier-1 (`ingest.cache`).

Scritti come `unittest.TestCase`: girano subito con la sola stdlib
(`python3 engine/tests/test_cache.py` oppure `python3 -m unittest`) e restano
raccoglibili da pytest quando il venv sarà pronto. Nessuna dipendenza esterna.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Package non installato (niente venv): rendo importabile engine/src.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ingest.cache import RELATION_SOURCES, SCHEMA_VERSION, Cache  # noqa: E402


class SchemaTest(unittest.TestCase):
    def test_schema_version_pragma(self) -> None:
        with Cache(":memory:") as cache:
            self.assertEqual(cache.schema_version, SCHEMA_VERSION)


class PaperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = Cache(":memory:")

    def tearDown(self) -> None:
        self.cache.close()

    def test_upsert_and_get_roundtrip(self) -> None:
        self.assertFalse(self.cache.has_paper("111"))
        self.cache.upsert_paper(
            "111",
            pub_date="2010-05-01",
            journal="Gut",
            title="Dysbiosis and cancer",
            abstract="An abstract.",
            raw={"pmid": "111", "nested": {"b": 1, "a": 2}},
            fetched_at="2026-07-20T00:00:00+00:00",
        )
        self.assertTrue(self.cache.has_paper("111"))
        row = self.cache.get_paper("111")
        assert row is not None
        self.assertEqual(row["journal"], "Gut")
        self.assertEqual(row["abstract"], "An abstract.")
        # raw_json serializzato in modo deterministico (chiavi ordinate).
        self.assertEqual(row["raw_json"], '{"nested": {"a": 2, "b": 1}, "pmid": "111"}')

    def test_upsert_is_last_write_wins(self) -> None:
        for title in ("v1", "v2"):
            self.cache.upsert_paper(
                "1", pub_date="2011", journal="J", title=title, abstract="", raw={}
            )
        self.assertEqual(self.cache.count_papers(), 1)
        row = self.cache.get_paper("1")
        assert row is not None
        self.assertEqual(row["title"], "v2")

    def test_missing_paper_is_none(self) -> None:
        self.assertIsNone(self.cache.get_paper("nope"))

    def test_iter_pmids_sorted(self) -> None:
        for pmid in ("3", "1", "2"):
            self.cache.upsert_paper(
                pmid, pub_date="2000", journal=None, title=None, abstract=None, raw={}
            )
        self.assertEqual(list(self.cache.iter_pmids()), ["1", "2", "3"])

    def test_year_counts_ignores_nonnumeric_and_null(self) -> None:
        data = {
            "a": "2010-01-01",
            "b": "2010-12-31",
            "c": "2015",
            "d": None,          # pub_date mancante -> ignorato
            "e": "n/a",         # non numerico -> ignorato
        }
        for pmid, pub_date in data.items():
            self.cache.upsert_paper(
                pmid, pub_date=pub_date, journal=None, title=None, abstract=None, raw={}
            )
        self.assertEqual(self.cache.year_counts(), {2010: 2, 2015: 1})
        self.assertEqual(self.cache.count_papers(), 5)


class AnnotationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = Cache(":memory:")

    def tearDown(self) -> None:
        self.cache.close()

    def test_set_annotations_replaces(self) -> None:
        self.cache.set_annotations(
            "1",
            [
                {"entity_id": "MESH:D064806", "entity_type": "Disease", "mention": "dysbiosis",
                 "offset": 10},
                {"entity_id": "GENE:7124", "entity_type": "Gene", "mention": "TNF", "offset": 40},
            ],
        )
        self.assertEqual(len(self.cache.get_annotations("1")), 2)
        # Un secondo set sostituisce (idempotenza sul re-ingest), non accumula.
        self.cache.set_annotations("1", [{"entity_id": "MESH:D064806"}])
        rows = self.cache.get_annotations("1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_id"], "MESH:D064806")

    def test_offset_column_is_stored(self) -> None:
        self.cache.set_annotations("2", [{"entity_id": "X", "offset": 7}])
        rows = self.cache.get_annotations("2")
        self.assertEqual(rows[0]["offset"], 7)


class RelationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = Cache(":memory:")

    def tearDown(self) -> None:
        self.cache.close()

    def test_set_and_get_relations(self) -> None:
        self.cache.set_relations(
            "pubtator3",
            "1",
            [{"subj_id": "A", "predicate": "associated_with", "obj_id": "B"}],
        )
        rows = self.cache.get_relations(pmid="1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "pubtator3")
        self.assertEqual(rows[0]["predicate"], "associated_with")

    def test_set_relations_replaces_per_source_pmid(self) -> None:
        self.cache.set_relations("cooccur", "1", [{"subj_id": "A", "obj_id": "B"}])
        self.cache.set_relations("cooccur", "1", [{"subj_id": "A", "obj_id": "C"}])
        rows = self.cache.get_relations(pmid="1", source="cooccur")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["obj_id"], "C")

    def test_relations_from_different_sources_coexist(self) -> None:
        self.cache.set_relations("cooccur", "1", [{"subj_id": "A", "obj_id": "B"}])
        self.cache.set_relations("pubtator3", "1", [{"subj_id": "A", "obj_id": "B"}])
        self.assertEqual(len(self.cache.get_relations(pmid="1")), 2)
        self.assertEqual(len(self.cache.get_relations(pmid="1", source="cooccur")), 1)

    def test_invalid_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.cache.set_relations("neo4j", "1", [{"subj_id": "A", "obj_id": "B"}])


class LlmExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = Cache(":memory:")

    def tearDown(self) -> None:
        self.cache.close()

    def test_cache_miss_then_hit(self) -> None:
        self.assertIsNone(self.cache.get_llm_extraction("hash-1"))
        self.cache.upsert_llm_extraction(
            pmid="1", model="claude-haiku-4-5", prompt_hash="hash-1",
            response={"relations": []}, created_at="2026-07-20T00:00:00+00:00",
        )
        row = self.cache.get_llm_extraction("hash-1")
        assert row is not None
        self.assertEqual(row["model"], "claude-haiku-4-5")

    def test_upsert_overwrites_same_prompt_hash(self) -> None:
        for model in ("m1", "m2"):
            self.cache.upsert_llm_extraction(
                pmid="1", model=model, prompt_hash="h", response={}, created_at="t",
            )
        row = self.cache.get_llm_extraction("h")
        assert row is not None
        self.assertEqual(row["model"], "m2")


class PipelineRunTest(unittest.TestCase):
    def test_start_and_get_run(self) -> None:
        with Cache(":memory:") as cache:
            cache.start_run(
                "run-1",
                git_sha="abc123",
                config_snapshot={"seed": 42, "corridor": "microbiome_cancer"},
                split="dev",
                graph_max_date="2010-12-31",
                created_at="2026-07-20T00:00:00+00:00",
            )
            row = cache.get_run("run-1")
            assert row is not None
            self.assertEqual(row["split"], "dev")
            self.assertEqual(row["graph_max_date"], "2010-12-31")
            self.assertIn('"seed": 42', row["config_snapshot_json"])


class OfflinePersistenceTest(unittest.TestCase):
    """Determinismo del re-run offline: riaprendo lo stesso file i dati ci sono ancora."""

    def test_data_persists_across_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "cache.sqlite3"
            with Cache(db) as c1:
                c1.upsert_paper(
                    "42", pub_date="2012", journal="J", title="t", abstract="a", raw={"k": "v"}
                )
            # Nuova connessione sullo stesso file: nessun ri-download necessario.
            with Cache(db) as c2:
                self.assertTrue(c2.has_paper("42"))
                self.assertEqual(c2.count_papers(), 1)
                self.assertEqual(c2.schema_version, SCHEMA_VERSION)

    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "nested" / "dir" / "cache.sqlite3"
            with Cache(db) as c:
                self.assertTrue(Path(db).parent.is_dir())
                self.assertEqual(c.count_papers(), 0)


class RelationSourcesTest(unittest.TestCase):
    def test_expected_sources(self) -> None:
        # Le sorgenti fissate in DesignArchitecture §6.1.
        self.assertEqual(RELATION_SOURCES, {"semmeddb", "pubtator3", "cooccur", "llm"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
