"""Turn-progress events for server-sent events (spec §6.26 L11, L8).

An in-process publish/subscribe bus. Subscriptions are keyed by (tenant, investigation): a subscriber can only ever receive events for a key built
from ITS OWN session's tenant, so guessing another tenant's investigation id yields an empty stream, never their events. Events carry only a kind,
a time offset and a small whitelist of non-sensitive labels (route, key, status): never a figure, an answer or a finding value.

Honest limits: the bus lives in one process. With several API workers a subscriber may be connected to a different worker than the one running
the turn; it then simply receives nothing, and the client falls back to polling findings (the transport spec L11 names as the fallback). Making
this cross-worker is the Redis item (V1.1). A queue is bounded: a slow subscriber loses the oldest events, never blocks a turn.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

from backend.ceo.runtime import EventSink, TurnEvent

_SAFE_DATA_KEYS = ("route", "routeKey", "source", "action", "entry", "findingId", "status", "mode")
_QUEUE_SIZE = 200

Key = tuple[UUID, UUID]
DONE = "TURN_DONE"  # synthetic: the turn finished (any outcome); the stream ends after it


def _public(event: TurnEvent) -> dict[str, Any]:
    data = {k: v for k, v in event.data.items() if k in _SAFE_DATA_KEYS and isinstance(v, (str, int, bool, type(None)))}
    return {"kind": event.kind, "atMs": event.at_ms, "data": data}


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[Key, list[queue.Queue[dict[str, Any] | None]]] = {}

    def subscribe(self, tenant_id: UUID, investigation_id: UUID) -> queue.Queue[dict[str, Any] | None]:
        q: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_QUEUE_SIZE)
        with self._lock:
            self._subs.setdefault((tenant_id, investigation_id), []).append(q)
        return q

    def unsubscribe(self, tenant_id: UUID, investigation_id: UUID, q: queue.Queue[dict[str, Any] | None]) -> None:
        with self._lock:
            subs = self._subs.get((tenant_id, investigation_id), [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subs.pop((tenant_id, investigation_id), None)

    def subscriber_count(self, tenant_id: UUID, investigation_id: UUID) -> int:
        with self._lock:
            return len(self._subs.get((tenant_id, investigation_id), []))

    def _put(self, tenant_id: UUID, investigation_id: UUID, item: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._subs.get((tenant_id, investigation_id), []))
        for q in targets:
            try:
                q.put_nowait(item)
            except queue.Full:
                try:
                    q.get_nowait()  # drop the oldest, keep the newest: a slow reader never blocks a turn
                    q.put_nowait(item)
                except (queue.Empty, queue.Full):
                    pass

    def sink_for(self, tenant_id: UUID, investigation_id: UUID) -> EventSink:
        def sink(event: TurnEvent) -> None:
            self._put(tenant_id, investigation_id, _public(event))

        return sink

    def done(self, tenant_id: UUID, investigation_id: UUID, *, status: str) -> None:
        self._put(tenant_id, investigation_id, {"kind": DONE, "atMs": 0, "data": {"status": status}})


_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


def chain(*sinks: Callable[[TurnEvent], None] | None) -> EventSink:
    live = [s for s in sinks if s is not None]

    def sink(event: TurnEvent) -> None:
        for s in live:
            s(event)

    return sink
