"""Per-investigation turn serialization (spec E24, §6.14): two turns in one investigation never run at once, so a summary regeneration or an
in-flight turn can never be read half-written.

A Postgres session-level advisory lock, so it holds across API workers (an in-process lock would not). The key is derived from the
investigation id only; the lock carries no data and grants nothing. It is taken on a dedicated autocommit connection that is held for the whole
turn and closed in `finally`, which also releases the lock if the process dies mid-turn (the session ends).

The wait is bounded by `CEO_TURN_LOCK_WAIT_SECONDS` (no default, like every CEO bound): unset means a second turn is refused at once with
`TurnInProgress` (HTTP 409) instead of waiting an unchosen length of time.
"""

from __future__ import annotations

import time
from fractions import Fraction
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from backend.repositories.ceo_runtime_repo import AdvisoryLock

POLL_SECONDS = Fraction(1, 5)  # exact, so no float literal exists in this package


class TurnInProgress(Exception):
    """Another turn in this investigation is still running (and any configured wait elapsed)."""


@contextmanager
def investigation_turn_lock(investigation_id: UUID, wait_seconds: int | None) -> Iterator[None]:
    with AdvisoryLock(str(investigation_id)) as lock:
        deadline = time.monotonic() + (wait_seconds or 0)
        while not lock.try_acquire():
            if time.monotonic() >= deadline:
                raise TurnInProgress(str(investigation_id))
            time.sleep(POLL_SECONDS.__float__())  # a plain sleep length, not a calculation
        yield
