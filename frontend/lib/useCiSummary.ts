"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { ApiError, apiFetch, type CiSummary } from "@/lib/api";

/** `GET /ci/summary`, with a 403 (role has no Competitor Intelligence access) kept separate from a
 * real failure — "you can't see this" is not an error to show a retry for. */
export function useCiSummary() {
  const { getToken } = useAuth();
  const [summary, setSummary] = useState<CiSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        setSummary(await apiFetch<CiSummary>("/api/v1/ci/summary", await getToken()));
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else setError(e instanceof ApiError ? e.message : "Could not reach the backend");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return { summary, error, forbidden };
}
