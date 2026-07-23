"""Test della costruzione del grafo A-B-C da una mini-cache (offline)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from graph.build_graph import NODE_A, NODE_C, build_corridor_graph
from ingest.cache import Cache

CONFIG: dict[str, Any] = {
    "corridor": {
        "A": {"label": "A-side", "mesh_anchors": ["Gastrointestinal Microbiome"]},
        "C": {"label": "C-side", "mesh_anchors": ["Neoplasms"]},
    }
}


def _paper(pmid: str, year: int, descriptors: list[str]) -> dict[str, Any]:
    return {
        "pmid": pmid,
        "pub_date": str(year),
        "pub_year": year,
        "journal": "J",
        "title": "t",
        "abstract": "a",
        "raw": {
            "MedlineCitation": {
                "PMID": pmid,
                "MeshHeadingList": [{"DescriptorName": d} for d in descriptors],
            }
        },
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }


def test_build_graph_anchors_and_first_year() -> None:
    db = tempfile.mktemp(suffix=".sqlite")
    cache = Cache(db)
    try:
        cache.upsert_papers([
            _paper("1", 2005, ["Gastrointestinal Microbiome", "Interleukin-6"]),
            _paper("2", 2001, ["Gastrointestinal Microbiome", "Interleukin-6"]),
            _paper("3", 2010, ["Neoplasms", "Interleukin-6"]),
            _paper("4", 2018, ["Neoplasms", "Butyrates"]),
        ])
        cache.set_corridor("A", ["1", "2"])
        cache.set_corridor("C", ["3", "4"])

        g = build_corridor_graph(cache, CONFIG)

        # Anchor esclusi dai B; IL-6 collega A e C, Butyrates tocca solo C.
        assert g.graph["total_papers"] == 4
        assert "Gastrointestinal Microbiome" not in g
        assert "Neoplasms" not in g

        il6 = g.nodes["Interleukin-6"]
        assert il6["a_df"] == 2 and il6["c_df"] == 1
        assert il6["a_first_year"] == 2001  # min sui paper A
        assert il6["c_first_year"] == 2010
        assert g.has_edge(NODE_A, "Interleukin-6")
        assert g.has_edge("Interleukin-6", NODE_C)

        but = g.nodes["Butyrates"]
        assert but["a_df"] == 0 and but["c_df"] == 1
        assert not g.has_edge(NODE_A, "Butyrates")
    finally:
        cache.close()
        Path(db).unlink(missing_ok=True)


def test_grounded_graph_filters_unsupported_descriptors() -> None:
    """In modalità grounded un descrittore conta solo nei paper dove è menzionato in una
    relazione estratta. Un descrittore mai relazionato (es. check-tag 'Adult') sparisce."""
    db = tempfile.mktemp(suffix=".sqlite")
    cache = Cache(db)
    try:
        cache.upsert_papers([
            _paper("1", 2001, ["Gastrointestinal Microbiome", "Interleukin-6", "Adult"]),
            _paper("2", 2005, ["Gastrointestinal Microbiome", "Interleukin-6", "Adult"]),
            _paper("3", 2010, ["Neoplasms", "Interleukin-6"]),
        ])
        cache.set_corridor("A", ["1", "2"])
        cache.set_corridor("C", ["3"])

        # Paper 1 e 3 affermano una relazione su IL-6; paper 2 NON ha relazioni.
        # 'Adult' non compare mai in una relazione -> filtrato in grounded.
        relations_by_pmid = {
            "1": [{"subject": "Interleukin-6", "predicate": "activates", "object": "cells"}],
            "2": [],
            "3": [{"subject": "tumor", "predicate": "secretes", "object": "Interleukin-6"}],
        }

        g_co = build_corridor_graph(cache, CONFIG)
        g_gr = build_corridor_graph(cache, CONFIG, relations_by_pmid=relations_by_pmid)

        assert g_co.graph["mode"] == "cooccur"
        assert g_gr.graph["mode"] == "relation"

        # Co-occorrenza: IL-6 in 2 paper A; 'Adult' presente come nodo.
        assert g_co.nodes["Interleukin-6"]["a_df"] == 2
        assert "Adult" in g_co

        # Grounded: paper 2 non supporta IL-6 (nessuna relazione) -> a_df scende a 1;
        # 'Adult' scompare del tutto (mai relazionato).
        assert g_gr.nodes["Interleukin-6"]["a_df"] == 1
        assert g_gr.nodes["Interleukin-6"]["c_df"] == 1
        assert "Adult" not in g_gr
    finally:
        cache.close()
        Path(db).unlink(missing_ok=True)
