"""Costruzione del grafo ABC ancorato ai corridoi, dai paper cacheati.

Modello (pilota): due super-nodi 'A' e 'C' (i corridoi microbioma / cancro) e un nodo
per ogni descrittore MeSH candidato B. Un arco A-B esiste se B compare in un paper del
corridoio A; B-C se compare in un paper del corridoio C. Ogni arco porta i PMID di
evidenza, gli anni e `first_year` (min) — cio' che rende il time-slicing (S2) una
semplice maschera sul grafo.

Scelta di `first_year`: si usa `pub_year` (anno di pubblicazione del fascicolo).
Caveat noto (vedi Sprint.md): `pub_year` diverge dall'asse di ricerca `pdat` ai bordi;
per l'ordinamento temporale del pilota e' la scelta piu' difendibile e viene documentata.

Il grafo descrittore-descrittore completo (per l'open discovery) e' rimandato a S3:
qui serve solo il cammino A-B-C per il verdetto S1/S2.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from ingest.cache import Cache
from relations.normalize import supported_descriptors

from .mesh import descriptors

NODE_A = "A"
NODE_C = "C"


@dataclass
class _BStats:
    a_years: list[int] = field(default_factory=list)
    c_years: list[int] = field(default_factory=list)
    a_pmids: list[str] = field(default_factory=list)
    c_pmids: list[str] = field(default_factory=list)
    total_df: int = 0


def build_corridor_graph(
    cache: Cache,
    config: dict[str, Any],
    *,
    relations_by_pmid: dict[str, list[dict[str, Any]]] | None = None,
    synonyms_of: Callable[[str], list[str]] | None = None,
) -> nx.Graph:
    """Costruisce il grafo A-B-C. Attributi utili per discovery/time-slicing sui nodi B:
    a_df, c_df, total_df, a_first_year, c_first_year.

    Definizione dell'arco A-B / B-C (l'unica cosa che cambia tra i due modi):
    - **co-occorrenza** (default, `relations_by_pmid=None`): B è ogni descrittore MeSH del
      paper. È il grafo che ha FALLITO S2 (co-occorrenza nuda non batte la frequenza).
    - **grounded** (`relations_by_pmid` fornito): B è solo un descrittore *relazionalmente
      supportato*, cioè menzionato come soggetto/oggetto in una relazione estratta dall'LLM
      da quell'abstract. Il time-slicing lavora sullo stesso spazio di nodi -> confronto pulito.
    """
    corridor = config["corridor"]
    a_label = corridor["A"]["label"]
    c_label = corridor["C"]["label"]
    anchors: set[str] = set(corridor["A"].get("mesh_anchors", [])) | set(
        corridor["C"].get("mesh_anchors", [])
    )
    grounded = relations_by_pmid is not None
    edge_source = "relation" if grounded else "cooccur"

    a_pmids = cache.pmids_in_corridor("A")
    c_pmids = cache.pmids_in_corridor("C")

    stats: dict[str, _BStats] = {}
    total_papers = 0
    rows = cache._conn.execute(  # noqa: SLF001 - lettura interna consentita nel motore
        "SELECT pmid, pub_year, raw_json FROM papers"
    ).fetchall()
    for r in rows:
        pmid = str(r["pmid"])
        year = r["pub_year"]
        in_a = pmid in a_pmids
        in_c = pmid in c_pmids
        if not (in_a or in_c):
            continue
        total_papers += 1
        art = json.loads(r["raw_json"])
        descs = {d for d in descriptors(art) if d not in anchors}
        if relations_by_pmid is not None:
            rels = relations_by_pmid.get(pmid, [])
            descs = supported_descriptors(descs, rels, synonyms_of=synonyms_of)
        for desc in descs:
            s = stats.setdefault(desc, _BStats())
            s.total_df += 1
            if in_a:
                s.a_pmids.append(pmid)
                if year is not None:
                    s.a_years.append(int(year))
            if in_c:
                s.c_pmids.append(pmid)
                if year is not None:
                    s.c_years.append(int(year))

    g: nx.Graph = nx.Graph()
    g.add_node(NODE_A, kind="anchor", corridor="A", label=a_label, df=len(a_pmids))
    g.add_node(NODE_C, kind="anchor", corridor="C", label=c_label, df=len(c_pmids))
    g.graph["total_papers"] = total_papers
    g.graph["mode"] = edge_source

    for desc, s in stats.items():
        a_df = len(s.a_pmids)
        c_df = len(s.c_pmids)
        g.add_node(
            desc,
            kind="mesh",
            label=desc,
            a_df=a_df,
            c_df=c_df,
            total_df=s.total_df,
            a_first_year=min(s.a_years) if s.a_years else None,
            c_first_year=min(s.c_years) if s.c_years else None,
        )
        if a_df:
            g.add_edge(
                NODE_A, desc, source=edge_source, weight=a_df,
                pmids=s.a_pmids, years=sorted(s.a_years),
                first_year=min(s.a_years) if s.a_years else None,
            )
        if c_df:
            g.add_edge(
                desc, NODE_C, source=edge_source, weight=c_df,
                pmids=s.c_pmids, years=sorted(s.c_years),
                first_year=min(s.c_years) if s.c_years else None,
            )
    return g
