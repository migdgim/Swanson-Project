"""Layer di estrazione relazioni (RelationSource).

Contratto astratto (`DesignArchitecture.md §7`): una sorgente di relazioni dietro
un'unica firma, sostituibile senza toccare il resto (SemMedDB | fallback LLM/co-occorrenza).
Qui vive l'implementazione LLM *grounded*: estrae SOLO relazioni presenti nel testo
dell'abstract, mai giudizi di plausibilità (guardrail anti-contaminazione del time-slicing).
"""
