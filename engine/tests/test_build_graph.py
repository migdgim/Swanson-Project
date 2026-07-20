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
