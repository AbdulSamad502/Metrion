"""P7e: the platform-wide daily provider-search counter (spec §6.8.5 `provider_daily_search_ceiling`).

A COMBINED ceiling on CMO provider searches per Asia/Kolkata calendar day, with separate per-provider tracking.
It counts CMO's own searches only: Product Intelligence uses the same Tavily and YouTube keys and is NOT visible
here, so this ceiling is a CMO guard, never a guarantee about total provider quota.

* `cmo_provider_usage` holds no tenant or seller data (platform-wide counters), so it is not a tenant table and has
  no RLS. The application role (`metrion_app`) has NO privilege on it: platform tables are not writable by the app.
* The only way the app touches it is two SECURITY DEFINER functions owned by the migration role. `search_path` is
  pinned, EXECUTE is revoked from PUBLIC and granted to `metrion_app` alone, and the day is derived INSIDE the
  function from `now()` (a caller cannot choose a day).
* `cmo_take_provider_slot` is atomic and concurrency-safe: it serialises on a transaction-scoped advisory lock for the
  day, reads the combined total, and increments only if the total is still below the ceiling. A slot is taken BEFORE
  a provider call and never refunded, so failed attempts count and cache hits (which never call this) do not.

Revision ID: 20261006_0003
Revises: 20261005_0002
Create Date: 2026-10-06
"""
from __future__ import annotations

from alembic import op

revision = "20261006_0003"
down_revision = "20261005_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cmo_provider_usage (
          usage_day  date        NOT NULL,
          provider   text        NOT NULL CHECK (provider IN ('TAVILY','YOUTUBE')),
          searches   integer     NOT NULL CHECK (searches >= 0),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (usage_day, provider)
        );
        REVOKE ALL ON TABLE cmo_provider_usage FROM PUBLIC;
        REVOKE ALL ON TABLE cmo_provider_usage FROM metrion_app;

        CREATE FUNCTION cmo_take_provider_slot(p_provider text, p_ceiling integer) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
        DECLARE
          v_day   date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
          v_total integer;
        BEGIN
          IF p_provider IS NULL OR p_provider NOT IN ('TAVILY', 'YOUTUBE') THEN
            RAISE EXCEPTION 'unknown provider %', p_provider;
          END IF;
          IF p_ceiling IS NULL OR p_ceiling < 1 THEN
            RAISE EXCEPTION 'ceiling must be a positive integer';
          END IF;
          PERFORM pg_advisory_xact_lock(hashtextextended('cmo_provider_usage:' || v_day::text, 0));
          SELECT COALESCE(sum(searches), 0) INTO v_total FROM public.cmo_provider_usage WHERE usage_day = v_day;
          IF v_total >= p_ceiling THEN
            RETURN false;
          END IF;
          INSERT INTO public.cmo_provider_usage (usage_day, provider, searches) VALUES (v_day, p_provider, 1)
          ON CONFLICT (usage_day, provider) DO UPDATE SET searches = cmo_provider_usage.searches + 1, updated_at = now();
          RETURN true;
        END
        $fn$;

        CREATE FUNCTION cmo_provider_usage_today() RETURNS TABLE (provider text, searches integer)
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
          SELECT u.provider, u.searches FROM public.cmo_provider_usage u
          WHERE u.usage_day = (now() AT TIME ZONE 'Asia/Kolkata')::date ORDER BY u.provider
        $fn$;

        REVOKE ALL ON FUNCTION cmo_take_provider_slot(text, integer) FROM PUBLIC;
        REVOKE ALL ON FUNCTION cmo_provider_usage_today() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION cmo_take_provider_slot(text, integer) TO metrion_app;
        GRANT EXECUTE ON FUNCTION cmo_provider_usage_today() TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS cmo_provider_usage_today();
        DROP FUNCTION IF EXISTS cmo_take_provider_slot(text, integer);
        DROP TABLE IF EXISTS cmo_provider_usage;
        """
    )
