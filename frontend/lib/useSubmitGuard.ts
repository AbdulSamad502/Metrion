"use client";

import { useRef } from "react";

/** Synchronous, ref-based guard against double-submits. `Button`'s `disabled` only takes
 * effect after React re-renders with `loading: true` — a fast double-click, or a second
 * Enter keypress, can dispatch both submit events before that first paint happens, so
 * relying on the `loading` state alone doesn't actually prevent two concurrent submits.
 * A ref updates immediately, no render involved, so the second call is dropped for real. */
export function useSubmitGuard() {
  const running = useRef(false);
  return async function guard<T>(fn: () => Promise<T>): Promise<T | undefined> {
    if (running.current) return undefined;
    running.current = true;
    try {
      return await fn();
    } finally {
      running.current = false;
    }
  };
}
