"use client";

import { useCallback, useEffect, useState } from "react";
import { DEFAULT_FILTERS, parseFilters, serializeFilters } from "./filters";
import type { FilterParams } from "./types";

/** The dashboard's filters, mirrored into the URL query. Starts at the defaults (what the server rendered), then adopts the URL after mount — never during
 * render — and follows back/forward. Updating replaces the history entry (a filter change is not a navigation) and keeps the hash tab. */
export function useCfoFilters(): [FilterParams, (next: Partial<FilterParams>) => void] {
  const [filters, setFilters] = useState<FilterParams>(DEFAULT_FILTERS);

  useEffect(() => {
    const read = () => setFilters(parseFilters(window.location.search));
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);

  const update = useCallback((next: Partial<FilterParams>) => {
    setFilters((cur) => {
      const merged = parseFilters(serializeFilters({ ...cur, ...next })); // re-validated: a bad value never reaches state or the URL
      const qs = serializeFilters(merged);
      window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`);
      return merged;
    });
  }, []);

  return [filters, update];
}
