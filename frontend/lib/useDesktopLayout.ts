"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(min-width: 768px)";
const WIDE_QUERY = "(min-width: 1280px)"; // Tailwind `xl`: the two-column hub; the right column then also carries the activity and results // Tailwind `md`: from here the specialist canvas leads the activity panel (below it, on a phone, it follows the activity)

const subscribeTo = (query: string) => (notify: () => void) => {
  const mq = typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query) : null;
  mq?.addEventListener("change", notify);
  return () => mq?.removeEventListener("change", notify);
};
const snapshotOf = (query: string) => () => (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query).matches : true);
const subscribe = subscribeTo(QUERY);
const snapshot = snapshotOf(QUERY);
const subscribeWide = subscribeTo(WIDE_QUERY);
const snapshotWide = snapshotOf(WIDE_QUERY);

/** True at the two-column breakpoint (1280 px), where the right column hosts the conversation AND the activity / results. */
export function useWideLayout(): boolean {
  return useSyncExternalStore(subscribeWide, snapshotWide, () => true);
}

/** True at the desktop breakpoint. Used where the ORDER of content in the document (and so the keyboard order) must differ between a phone and a desktop: CSS `order` would
 * leave focus jumping against what is on screen. Without `matchMedia` (server, tests) it is true, i.e. the desktop order. */
export function useDesktopLayout(): boolean {
  return useSyncExternalStore(subscribe, snapshot, () => true);
}
