"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createCeoClient, type HealthEntry } from "@/lib/ceo";
import type { HealthState } from "@/lib/useCeoHub";

/** The Overview's profit snapshot: the same persisted, backend-presented results the CEO Hub's "business at a glance" shows
 * (`GET /api/v1/ceo/state/health` — CFO bands and the latest saved P&L as verified display snapshots). Nothing is computed here.
 * There is still no portfolio-level profit/margin endpoint; until one exists this is the only honest source, and a missing result
 * says so instead of showing a number. */
export function useBusinessHealth(): { health: HealthState; refresh: () => void; refreshing: boolean } {
  const { getToken } = useAuth();
  const client = useMemo(() => createCeoClient(getToken), [getToken]);
  const [health, setHealth] = useState<HealthState>({ status: "loading", entries: [] });
  const [refreshing, setRefreshing] = useState(false); // a retry in flight: the shown results stay put, the button says so

  const alive = useRef(true); // a reply that arrives after the page is gone must not update it
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const { entries } = await client.getHealth();
      if (alive.current) setHealth({ status: "ready", entries });
    } catch {
      if (alive.current) setHealth((h) => ({ status: "error", entries: h.entries }));
    } finally {
      if (alive.current) setRefreshing(false);
    }
  }, [client]);

  useEffect(() => {
    (async () => {
      await refresh();
    })();
  }, [refresh]);

  return { health, refresh: () => void refresh(), refreshing };
}

/** The most recent as-of date among the saved results (ISO string comparison only; no arithmetic), for the freshness line. */
export function latestAsOf(entries: HealthEntry[]): string | null {
  const dates = entries.map((e) => e.asOf).filter((d): d is string => Boolean(d));
  return dates.length ? dates.reduce((a, b) => (a >= b ? a : b)) : null;
}

/** Same threshold the competitor view uses for "stale" (no research in over 7 days). A date comparison only: nothing here is money or a score. */
export const STALE_AFTER_DAYS = 7;
export const daysSince = (iso: string | null, now: number = Date.now()): number | null => {
  if (!iso) return null;
  const t = Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.floor((now - t) / 86_400_000));
};

