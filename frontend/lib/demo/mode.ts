"use client";

import { useSyncExternalStore } from "react";

/** Sample-data preview. It exists only where `NEXT_PUBLIC_ENABLE_DEMO_DATA=1` is set AND the build is not a production build (`NODE_ENV !== "production"`,
 * i.e. `next dev` or a test run), so a production deployment can never show it, flag or not. It is off until chosen. Switched on, the dashboards read
 * hand-written SAMPLE responses instead of the backend (see `respond.ts`), nothing is saved, and a permanent "Sample data" label says so on every page,
 * the print report included. The CEO Hub is never fed sample data: on its route this module reports "off", so its requests (and the shared shell's) stay real. */
export const DEMO_AVAILABLE = process.env.NEXT_PUBLIC_ENABLE_DEMO_DATA === "1" && process.env.NODE_ENV !== "production";
const HUB_PREFIX = "/dashboard/ceo-hub";
export const DEMO_KEY = "metrion.demo";

const listeners = new Set<() => void>();
let on = false;
let loaded = false;

function load(): boolean {
  if (!loaded) {
    loaded = true;
    try {
      on = window.localStorage.getItem(DEMO_KEY) === "1";
    } catch {
      /* storage unavailable: stay off */
    }
  }
  return DEMO_AVAILABLE && on;
}
const onHub = () => window.location.pathname === HUB_PREFIX || window.location.pathname.startsWith(`${HUB_PREFIX}/`);

/** True only when the preview is available in this build AND switched on in this browser. */
export const demoActive = (): boolean => (typeof window !== "undefined" ? load() && !onHub() : false);

export function setDemo(next: boolean): void {
  if (!DEMO_AVAILABLE) return;
  load();
  on = next;
  try {
    window.localStorage.setItem(DEMO_KEY, next ? "1" : "0");
  } catch {
    /* not remembered, still applied */
  }
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

export const useDemo = (): boolean => useSyncExternalStore(subscribe, demoActive, () => false);

/** Test seam. */
export function resetDemoForTests(): void {
  loaded = false;
  on = false;
}
