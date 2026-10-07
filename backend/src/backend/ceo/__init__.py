"""The CEO operating layer (docs/specs/ceo-agent-orchestration.md, CP1 2026-10-07) — B1 Foundation.

What lives here is the deterministic substrate every later checkpoint builds on: typed contracts
(`contract`), provenance resolution (`provenance`), the fixed action registry (`registry`), the single
dispatch choke point (`dispatch`) and the Business State read catalog (`business_state`).

There is NO classifier, composer, playbook or API route here yet (B2/B3/B4). Nothing in this package
computes a money figure, decides what the LLM may do, or talks to a model; `tests/unit/test_ceo_architecture.py`
enforces the import and arithmetic rules that keep it that way.
"""
