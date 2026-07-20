"""Tipi e contratto di `RelationSource`.

`Relation` normalizza ogni relazione (LLM grounded, PubTator3, co-occorrenza, SemMedDB)
nella stessa forma soggetto–predicato–oggetto ancorata a un PMID, con la frase di
evidenza testuale. `RelationSource` è il Protocol di `DesignArchitecture.md §7`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Relation:
    """Tripla grounded: le stringhe provengono dal testo dell'abstract, non da vocabolari
    esterni (la normalizzazione a MeSH/UMLS è un passo separato, a valle)."""

    subject: str
    predicate: str
    object: str
    pmid: str
    evidence: str  # frase/clausola verbatim dell'abstract che afferma la relazione
    source: str = "llm"


@dataclass
class Usage:
    """Contatori di token misurati (dalla risposta API, non stimati)."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ExtractionResult:
    pmid: str
    relations: list[Relation] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    cached: bool = False
    parse_ok: bool = True


class RelationSource(Protocol):
    """SemMedDB, PubTator3, co-occorrenza o estrazione LLM: stessa firma."""

    def relations_for(self, pmids: list[str]) -> Iterable[Relation]: ...
