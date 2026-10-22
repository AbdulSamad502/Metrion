"use client";

import { useSyncExternalStore } from "react";
import type { Period } from "./dashboard";

const DAY_MS = 86_400_000;
const iso = (d: Date): string => d.toISOString().slice(0, 10);

let cached: Period | null = null;
const noSubscribe = (): (() => void) => () => {};
const snapshot = (): Period => {
  if (cached === null) {
    const now = new Date();
    cached = { start: iso(new Date(now.getTime() - 89 * DAY_MS)), end: iso(now) };
  }
  return cached;
};

/** The period shown until the seller picks one: the last 90 days ending today. The server snapshot is null, so the server and the first client render agree and the
 * period appears right after hydration. A date range, not money — the only arithmetic here is on calendar days. */
export function useDefaultPeriod(): Period | null {
  return useSyncExternalStore(noSubscribe, snapshot, () => null);
}
