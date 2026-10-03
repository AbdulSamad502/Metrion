"""Slim CMO generators (P3) - the PURE core: prompts, parsing, retry loops, outcomes.

Nothing here touches a database, a network, a clock or a model implementation. A generator takes
an `LlmProvider` (a Protocol), plain dataclasses and an integer retry bound, and returns an
`Outcome`. The deterministic validators of P2 are authoritative over everything a provider
returns (spec §6.3, §6.4, C9); provider output is untrusted text.

Recommend-only (spec §0): no generator writes anywhere.
"""
