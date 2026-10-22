"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { isActive, pollDelayMs, type JobView } from "./ingest";

export type JobState = { status: "loading" | "ready" | "error"; job: JobView | null; error: string | null };

/** Follow one ingestion job until it finishes. Polls `GET /cfo/jobs/{id}`; reported progress never goes backwards (a stale or out-of-order response cannot move the
 * bar back); the poll slows down while nothing changes and stops at a terminal state or when the component goes away. A failed poll shows its reason and keeps
 * trying — a blip must not look like a failed upload. */
export function useJob(jobId: string | null, initial?: JobView | null): JobState & { reload: () => void } {
  const { getToken } = useAuth();
  const [state, setState] = useState<JobState>({ status: initial ? "ready" : "loading", job: initial ?? null, error: null });
  const [tick, setTick] = useState(0);
  const best = useRef<number>(0);

  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let quiet = 0;
    best.current = initial?.progressRows ?? 0;

    const poll = async () => {
      try {
        const token = await getToken();
        const next = await apiFetch<JobView>(`/api/v1/cfo/jobs/${jobId}`, token);
        if (stopped) return;
        const progressed = next.progressRows > best.current;
        quiet = progressed ? 0 : quiet + 1;
        best.current = Math.max(best.current, next.progressRows);
        const shown = next.progressRows < best.current ? { ...next, progressRows: best.current } : next;
        setState({ status: "ready", job: shown, error: null });
        if (isActive(next.status)) timer = setTimeout(poll, pollDelayMs(quiet));
      } catch (e) {
        if (stopped) return;
        quiet += 1;
        setState((s) => ({ ...s, status: s.job ? "ready" : "error", error: friendlyApiError(e, "Could not check on this upload") }));
        timer = setTimeout(poll, pollDelayMs(quiet));
      }
    };
    poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, tick]);

  return { ...state, reload: () => setTick((n) => n + 1) };
}
