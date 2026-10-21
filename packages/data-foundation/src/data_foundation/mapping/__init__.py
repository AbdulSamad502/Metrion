"""Semantic column mapping for unfamiliar report formats (cfo-data-intelligence.md §6.4).

A model may only *propose* a mapping from a closed vocabulary; deterministic validation and seller
confirmation decide. Nothing here calls an LLM — proposals arrive as already-parsed data, so every
rule is testable with mocked proposals.
"""
