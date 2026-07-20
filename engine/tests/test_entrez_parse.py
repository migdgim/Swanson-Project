"""Test della logica *pura* del client Entrez: parsing dei record e orchestrazione
`download_corpus`. NON tocca la rete né Biopython.

Il layer di rete (`Bio.Entrez.esearch/efetch`) resta non eseguito finché non ci
sono venv e API key; qui si esercita tutto ciò che non dipende da Bio, con input
sintetici che imitano la struttura di `Entrez.read` (dict/list/str).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ingest.cache import Cache  # noqa: E402
from ingest.entrez_client import (  # noqa: E402
    CorpusReport,
    ParsedPaper,
    _extract_abstract,
    _month_num,
    _parse_article,
    _to_plain,
    download_corpus,
)


def _article(
    *,
    pmid: str = "111",
    article_date: dict | None = None,
    pubdate: dict | None = None,
    title: str = "A title",
    journal: str = "Gut",
    abstract=None,
) -> dict:
    """Costruisce un PubmedArticle sintetico con la struttura di Entrez.read."""
    art: dict = {
        "ArticleTitle": title,
        "Journal": {"Title": journal, "JournalIssue": {"PubDate": pubdate or {}}},
    }
    if article_date is not None:
        art["ArticleDate"] = [article_date]
    if abstract is not None:
        art["Abstract"] = {"AbstractText": abstract}
    return {"MedlineCitation": {"PMID": pmid, "Article": art}}


class ParseArticleTest(unittest.TestCase):
    def test_full_article(self) -> None:
        art = _article(
            pmid="12345",
            article_date={"Year": "2010", "Month": "05", "Day": "14"},
            title="Dysbiosis and cancer",
            journal="Nature",
            abstract=["Background text.", "Results text."],
        )
        paper = _parse_article(art)
        assert paper is not None
        self.assertEqual(paper.pmid, "12345")
        self.assertEqual(paper.pub_date, "2010-05-14")
        self.assertEqual(paper.title, "Dysbiosis and cancer")
        self.assertEqual(paper.journal, "Nature")
        self.assertEqual(paper.abstract, "Background text.\nResults text.")

    def test_missing_citation_returns_none(self) -> None:
        self.assertIsNone(_parse_article({"PubmedData": {}}))

    def test_pubdate_year_only(self) -> None:
        paper = _parse_article(_article(pubdate={"Year": "2015"}))
        assert paper is not None
        self.assertEqual(paper.pub_date, "2015")

    def test_pubdate_year_month(self) -> None:
        paper = _parse_article(_article(pubdate={"Year": "2015", "Month": "Jan"}))
        assert paper is not None
        self.assertEqual(paper.pub_date, "2015-01")

    def test_medline_date_fallback(self) -> None:
        paper = _parse_article(_article(pubdate={"MedlineDate": "2010 Jan-Feb"}))
        assert paper is not None
        self.assertEqual(paper.pub_date, "2010")

    def test_no_date_is_none(self) -> None:
        paper = _parse_article(_article(pubdate={}))
        assert paper is not None
        self.assertIsNone(paper.pub_date)

    def test_pub_date_always_starts_with_year(self) -> None:
        # Contratto con Cache.year_counts(): la data inizia con 4 cifre o è None.
        for pubdate in ({"Year": "2011"}, {"Year": "2011", "Month": "Mar"},
                        {"MedlineDate": "2011 Spring"}):
            paper = _parse_article(_article(pubdate=pubdate))
            assert paper is not None and paper.pub_date is not None
            self.assertTrue(paper.pub_date[:4].isdigit())

    def test_article_date_preferred_over_journal_pubdate(self) -> None:
        paper = _parse_article(
            _article(
                article_date={"Year": "2010", "Month": "06", "Day": "01"},
                pubdate={"Year": "2009"},
            )
        )
        assert paper is not None
        self.assertEqual(paper.pub_date, "2010-06-01")


class AbstractExtractTest(unittest.TestCase):
    def test_single_string(self) -> None:
        self.assertEqual(_extract_abstract({"Abstract": {"AbstractText": "solo testo"}}),
                         "solo testo")

    def test_sections_joined(self) -> None:
        self.assertEqual(
            _extract_abstract({"Abstract": {"AbstractText": ["A", "B", "C"]}}), "A\nB\nC"
        )

    def test_absent(self) -> None:
        self.assertIsNone(_extract_abstract({}))


class MonthNumTest(unittest.TestCase):
    def test_names(self) -> None:
        self.assertEqual(_month_num("Jan"), 1)
        self.assertEqual(_month_num("december"), 12)

    def test_numeric(self) -> None:
        self.assertEqual(_month_num("03"), 3)
        self.assertEqual(_month_num("7"), 7)

    def test_invalid(self) -> None:
        self.assertIsNone(_month_num("Foo"))
        self.assertIsNone(_month_num("13"))
        self.assertIsNone(_month_num(None))


class ToPlainTest(unittest.TestCase):
    def test_nested_conversion(self) -> None:
        # str/int subtypes -> tipi puri, ricorsivo su dict/list.
        out = _to_plain({"a": [1, "x", {"b": True, "c": None}]})
        self.assertEqual(out, {"a": [1, "x", {"b": True, "c": None}]})


class CorpusReportTest(unittest.TestCase):
    def test_as_line(self) -> None:
        line = CorpusReport(query="q", found=10, fetched=7, cached_total=7).as_line()
        self.assertIn("found=10", line)
        self.assertIn("fetched=7", line)
        self.assertIn("cached_total=7", line)


class _FakeClient:
    """Sostituto di EntrezClient per testare l'orchestrazione senza rete."""

    def __init__(self, pmids: list[str], papers: list[ParsedPaper]) -> None:
        self._pmids = pmids
        self._papers = {p.pmid: p for p in papers}
        self.fetched_ids: list[str] | None = None

    def search_pmids(self, query: str, *, retmax: int, min_year=None) -> list[str]:
        return self._pmids

    def fetch_records(self, pmids, *, batch_size: int = 200):
        self.fetched_ids = list(pmids)
        for pmid in pmids:
            if pmid in self._papers:
                yield self._papers[pmid]


def _paper(pmid: str, year: str) -> ParsedPaper:
    return ParsedPaper(pmid=pmid, pub_date=year, journal="J", title="t", abstract="a", raw={})


class DownloadCorpusTest(unittest.TestCase):
    def test_downloads_all_and_reports(self) -> None:
        client = _FakeClient(["1", "2", "3"], [_paper("1", "2010"), _paper("2", "2011"),
                                               _paper("3", "2012")])
        with Cache(":memory:") as cache:
            report = download_corpus(client, cache, query="q", retmax=100)
            self.assertEqual(report.found, 3)
            self.assertEqual(report.fetched, 3)
            self.assertEqual(report.cached_total, 3)
            self.assertEqual(cache.year_counts(), {2010: 1, 2011: 1, 2012: 1})

    def test_skips_already_cached(self) -> None:
        client = _FakeClient(["1", "2"], [_paper("1", "2010"), _paper("2", "2011")])
        with Cache(":memory:") as cache:
            # PMID "1" già in cache: non va ri-scaricato.
            cache.upsert_paper("1", pub_date="2010", journal="J", title="t",
                               abstract="a", raw={})
            report = download_corpus(client, cache, query="q", retmax=100)
            self.assertEqual(client.fetched_ids, ["2"])  # solo il nuovo
            self.assertEqual(report.found, 2)
            self.assertEqual(report.fetched, 1)
            self.assertEqual(report.cached_total, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
