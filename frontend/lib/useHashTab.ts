"use client";

import { useCallback, useEffect, useState } from "react";

/** The active tab, mirrored into `location.hash` so a tab is linkable and survives a refresh.
 * Starts on `fallback` (what the server rendered), then adopts a valid hash after mount — never
 * during render, so there is no hydration mismatch. Back/forward changes are followed. */
export function useHashTab(ids: readonly string[], fallback: string): [string, (id: string) => void] {
  const [active, setActive] = useState(fallback);

  useEffect(() => {
    const read = () => {
      const h = window.location.hash.replace(/^#/, "");
      setActive(ids.includes(h) ? h : fallback);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = useCallback((id: string) => {
    setActive(id);
    window.history.replaceState(null, "", `#${id}`);
  }, []);

  return [active, select];
}
