"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { friendlyApiError } from "@/lib/apiErrors";
import { ApiError, apiFetch, type CiSummary } from "@/lib/api";

/** `GET /ci/summary`, with a 403 (role has no Competitor Intelligence access) kept separate from a
 * real failure — "you can't see this" is not an error to show a retry for. */
export function useCiSummary() {
  const { getToken } = useAuth();
  const [summary, setSummary] = useState<CiSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  useEffect(() => {
    let alive = true; // a reply that arrives after the page is gone must not update it
    (async () => {
      try {
        const s = await apiFetch<CiSummary>("/api/v1/ci/summary", await getToken());
        if (alive) {
          setSummary(s);
          setError(null);
        }
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else setError(friendlyApiError(e, "Could not reach the backend"));
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);
  // A failed re-read keeps the last counts that loaded (`summary`) and sets `error`; `reload` tries again.
  return { summary, error, forbidden, reload };
}
