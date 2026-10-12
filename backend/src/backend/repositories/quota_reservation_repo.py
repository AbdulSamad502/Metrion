"""Quota reservations for PI (and any other agent) — a neutral door onto the existing reservation machinery (approval prerequisite R6, owner decision F3).

The table is still named `cmo_quota_reservation` (migration 20261004_0005) and `cmo_quota_repo.reserve()` is already agent-generic: it serialises on
(tenant, agent, meter, period) with `pg_advisory_xact_lock`, expires stale reservations, counts recorded events + unexpired reservations against the cap and
inserts the reservation, all in one short transaction, with an idempotent active reservation per (tenant, agent, meter, request_key). It exists because a plain
check-then-record let 7 of 8 concurrent requests pass a cap of 1. PI reuses it unchanged (`agent_code = 'PI'` or `'SHARED'`); the `cmo_` prefix is a known naming
wart, deliberately not renamed here (no schema churn in this checkpoint). A reservation is quota protection, never a billing record.
"""

from __future__ import annotations

from backend.repositories.cmo_quota_repo import ReservationInProgress, Reserved, ReserveDenied, finish, reserve

__all__ = ["ReservationInProgress", "Reserved", "ReserveDenied", "finish", "reserve"]
