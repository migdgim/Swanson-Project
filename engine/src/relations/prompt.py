"""Prompt di estrazione relazioni *grounded* (versionato).

Guardrail non negoziabile (`AGENTS.md`, `DesignArchitecture.md §5/§6`): l'LLM può SOLO
estrarre relazioni **esplicitamente presenti nel testo**. Mai inferire, mai usare
conoscenza esterna, mai giudicare plausibilità/novità/importanza di un legame — altrimenti
contaminerebbe il time-slicing con "conoscenza dal futuro".

`PROMPT_VERSION` entra nella chiave di cache: cambiare il prompt invalida le estrazioni.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

_INSTRUCTIONS = """You are a biomedical relation extractor. Extract ONLY relations that are \
EXPLICITLY stated in the abstract text provided below.

STRICT RULES:
- Extract subject-predicate-object triples where BOTH the subject and the object are \
entities named in the text.
- Use wording taken verbatim from the abstract. Do NOT normalize to external vocabularies, \
do NOT add synonyms, do NOT expand abbreviations beyond what the text does.
- The "evidence" field MUST be a sentence or clause copied verbatim from the abstract that \
states the relation.
- Do NOT infer, guess, or use any knowledge beyond this abstract.
- Do NOT assess plausibility, importance, novelty, or whether any relation is interesting \
or true in the real world. You only report what the text asserts.
- If the abstract states no explicit relation between named entities, return an empty list.

Return STRICT JSON only, exactly matching this shape:
{"relations": [{"subject": "...", "predicate": "...", "object": "...", "evidence": "..."}]}
No prose, no markdown, no code fences."""


def build_prompt(title: str | None, abstract: str) -> str:
    """Assembla il prompt per un singolo abstract. Deterministico (nessun timestamp/ID)."""
    header = f"TITLE: {title.strip()}" if title else "TITLE: (none)"
    return f"{_INSTRUCTIONS}\n\n{header}\n\nABSTRACT:\n{abstract.strip()}\n"
