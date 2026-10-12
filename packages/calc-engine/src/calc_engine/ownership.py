"""Run ownership hooks (R5). The host application replaces `claim` and `release` at start-up; until it does they do nothing, so this package stays usable on its own.

`claim(run_id)` is called BEFORE a `RUNNING` row is inserted and `release(run_id)` AFTER the row reaches a terminal status. While the claim is held the row has a live owner;
a row whose owner is gone is settled by the host's recovery sweep. See `docs/planning/r5-stuck-running-findings-2026-10-12.md`."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID


def _nothing(run_id: UUID) -> None:
    return None


claim: Callable[[UUID], None] = _nothing
release: Callable[[UUID], None] = _nothing
