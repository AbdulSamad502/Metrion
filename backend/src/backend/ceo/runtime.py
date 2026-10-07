"""Runtime wiring, stage clock and the progressive-delivery event seam for CEO turns (spec §6.26 L1, L8, L9).

* `CeoRuntime` — everything a turn needs that is not the request: the two model handles (classification and composition may be
  different models, §6.26 L5), the registry, a clock, and the leg bounds. The bounds are CONFIGURATION WITHOUT DEFAULTS (§6.12
  rule 5): a missing value means the playbook refuses with `CONFIG_MISSING`; nothing is guessed here.
* `StageClock` — monotonic stage timings in whole milliseconds (`perf_counter_ns`, no floats), safe to use from the leg threads.
  Persisted on `investigation_turn.stage_timings`. No latency target is encoded anywhere.
* `TurnEvent` / `EventSink` — the clean seam an SSE/WebSocket transport (B4) subscribes to: specialist findings are emitted AS EACH
  LEG COMPLETES, from the leg's own thread, before the answer is composed. Today the HTTP route collects the events and returns
  them with the turn result, and the findings endpoint can be polled.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from backend.ceo.registry import ActionRegistry, get_registry
from backend.llm.model import LlmModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CeoRuntime:
    classifier: LlmModel
    composer: LlmModel | None  # None => answers needing prose use the template (flagged TEMPLATE_FALLBACK)
    leg_timeout_seconds: int | None  # None => CONFIG_MISSING for any playbook with legs
    max_legs: int | None  # None => CONFIG_MISSING
    clock: Callable[[], datetime] = utcnow
    registry: ActionRegistry = field(default_factory=get_registry)


@dataclass(frozen=True, slots=True)
class TurnEvent:
    kind: str  # TURN_RECEIVED | TURN_ADMITTED | CLASSIFIED | PLAN_VALIDATED | STATE_READ | LEG_STARTED | LEG_FINISHED | SYNTHESIS_STARTED | ANSWER_READY | TURN_DENIED | TURN_FAILED
    at_ms: int  # milliseconds since the request was received
    data: dict[str, Any] = field(default_factory=dict)


class EventSink(Protocol):
    def __call__(self, event: TurnEvent) -> None: ...


class StageClock:
    """Thread-safe stage recorder. `span(name)` records `{startMs, endMs}` relative to request receipt; `event` stamps an instant."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter_ns()
        self.received_at = utcnow()
        self._lock = threading.Lock()
        self.stages: dict[str, dict[str, int]] = {}
        self.legs: list[dict[str, Any]] = []
        self.extras: dict[str, int] = {}

    def now_ms(self) -> int:
        return (time.perf_counter_ns() - self._t0) // 1_000_000

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        start = self.now_ms()
        try:
            yield
        finally:
            with self._lock:
                self.stages[name] = {"startMs": start, "endMs": self.now_ms()}

    def note(self, name: str, value_ms: int) -> None:
        with self._lock:
            self.extras[name] = value_ms

    def leg_started(self, action_key: str) -> int:
        start = self.now_ms()
        with self._lock:
            self.legs.append({"action": action_key, "startMs": start, "endMs": None, "status": "RUNNING"})
        return start

    def leg_finished(self, action_key: str, status: str) -> None:
        end = self.now_ms()
        with self._lock:
            for leg in self.legs:
                if leg["action"] == action_key and leg["endMs"] is None:
                    leg["endMs"], leg["status"] = end, status
                    return

    def to_json(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requestReceivedAt": self.received_at.isoformat(), "stages": dict(self.stages), "extras": dict(self.extras), "legs": [dict(leg) for leg in self.legs],
                "totalMs": self.now_ms(),
            }


class EventLog:
    """A collecting, thread-safe sink; also forwards to an optional downstream sink (the future SSE transport)."""

    def __init__(self, clock: StageClock, downstream: EventSink | None = None) -> None:
        self._clock, self._down = clock, downstream
        self._lock = threading.Lock()
        self.events: list[TurnEvent] = []

    def emit(self, kind: str, **data: Any) -> None:
        event = TurnEvent(kind, self._clock.now_ms(), data)
        with self._lock:
            self.events.append(event)
        if self._down is not None:
            try:
                self._down(event)
            except Exception:  # noqa: BLE001 — a failing subscriber must never break a turn
                pass
