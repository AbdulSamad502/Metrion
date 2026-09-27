"""Shared pytest fixtures.

CP1 scaffolding only (`twinkly-mapping-canyon.md`): no CFO-specific fakes exist yet — those
land with CP2's composition logic (Brain-3 `LlmProvider` fakes, engine-call fakes) and CP3's
tests. This file exists so `pytest packages/cfo/tests` has somewhere to wire fixtures into
without every future test file needing to invent its own conftest from scratch.
"""

from __future__ import annotations
