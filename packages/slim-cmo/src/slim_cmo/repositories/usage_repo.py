"""The platform-wide daily provider-search counter (migration 20261006_0003). Calls only the two SECURITY DEFINER
functions as the application role; it has no privilege on the table itself. Not tenant-scoped: the counters hold no
tenant or seller data, so no tenant context is set (and none is needed or wanted).

Fails closed: any database error propagates to the caller, which must NOT make the provider call.
"""

from __future__ import annotations

from sqlalchemy import text

from slim_cmo.repositories.tenant_context import get_engine

_TAKE = text("SELECT cmo_take_provider_slot(:provider, :ceiling)")
_TODAY = text("SELECT provider, searches FROM cmo_provider_usage_today()")


class PostgresSlotStore:
    def take_slot(self, provider: str, ceiling: int) -> bool:
        """Atomically take one search slot for today (Asia/Kolkata) unless the COMBINED total already reached
        `ceiling`. True = go ahead and call the provider; False = the daily ceiling is reached."""
        with get_engine().begin() as conn:
            return bool(conn.execute(_TAKE, {"provider": provider, "ceiling": ceiling}).scalar_one())

    def usage_today(self) -> dict[str, int]:
        with get_engine().begin() as conn:
            return {r.provider: int(r.searches) for r in conn.execute(_TODAY)}
