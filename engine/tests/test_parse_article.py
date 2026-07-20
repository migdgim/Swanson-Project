"""Test del parsing dei record PubMed (logica pura, offline, deterministica).

Coprono i punti fragili: estrazione di anno/data da forme diverse di PubDate,
join dell'abstract strutturato, e scarto dei record malformati.
"""

from __future__ import annotations

from typing import Any

from ingest.entrez_client import EntrezClient


def _article(pubdate: dict[str, Any], abstract: Any = None) -> dict[str, Any]:
    art: dict[str, Any] = {
        "ArticleTitle": "Test title",
        "Journal": {"Title": "Test Journal", "JournalIssue": {"PubDate": pubdate}},
    }
    if abstract is not None:
        art["Abstract"] = {"AbstractText": abstract}
    return {"MedlineCitation": {"PMID": "123", "Article": art}}


def test_pubdate_year_month_day() -> None:
    row = EntrezClient._parse_article(_article({"Year": "2013", "Month": "Mar", "Day": "5"}))
    assert row is not None
    assert row["pub_year"] == 2013
    assert row["pub_date"] == "2013-03-05"


def test_pubdate_year_only() -> None:
    row = EntrezClient._parse_article(_article({"Year": "2001"}))
    assert row is not None
    assert row["pub_year"] == 2001
    assert row["pub_date"] == "2001"


def test_pubdate_numeric_month() -> None:
    row = EntrezClient._parse_article(_article({"Year": "1999", "Month": "12"}))
    assert row is not None
    assert row["pub_date"] == "1999-12"


def test_pubdate_medline_string() -> None:
    row = EntrezClient._parse_article(_article({"MedlineDate": "2008 Winter"}))
    assert row is not None
    assert row["pub_year"] == 2008


def test_abstract_structured_join() -> None:
    row = EntrezClient._parse_article(
        _article({"Year": "2020"}, abstract=["Background text.", "Results text."])
    )
    assert row is not None
    assert row["abstract"] == "Background text.\nResults text."


def test_abstract_absent() -> None:
    row = EntrezClient._parse_article(_article({"Year": "2020"}))
    assert row is not None
    assert row["abstract"] is None


def test_malformed_record_dropped() -> None:
    assert EntrezClient._parse_article({"nope": True}) is None


def test_month_name_out_of_range() -> None:
    assert EntrezClient._month_num("13") is None
    assert EntrezClient._month_num("Foo") is None
    assert EntrezClient._month_num("Jul") == 7
