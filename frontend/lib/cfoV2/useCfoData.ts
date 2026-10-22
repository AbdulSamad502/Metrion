"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { isRefusal, type Refusal } from "./dashboard";

export type DataState<T> = { status: "loading" | "ready" | "refused" | "error"; data: T | null; refusal: Refusal | null; error: string | null; reload: () => void };

type Settled<T> = { key: string; status: "ready" | "refused" | "error"; data: T | null; refusal: Refusal | null; error: string | null };

/** Server state for one dashboard section: loading / ready / refused / error, independently of every other section. A change of path, query or reload aborts the request
 * in flight (so a slow earlier answer can never overwrite a newer one), and an answer that belongs to an earlier request is never shown for the current one — until the
 * current one settles the section reads as loading. `path: null` means "not ready to ask yet". */
export function useCfoData<T>(path: string | null, query: string): DataState<T> {
  const { getToken } = useAuth();
  const [tick, setTick] = useState(0);
  const key = `${path}?${query}#${tick}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (path === null) return;
    const ctl = new AbortController();
    (async () => {
      try {
        const token = await getToken();
        const body = await apiFetch<T | Refusal>(`/api/v1/cfo${path}${query ? `?${query}` : ""}`, token, { signal: ctl.signal });
        if (ctl.signal.aborted) return;
        if (isRefusal(body)) setSettled({ key, status: "refused", data: null, refusal: body, error: null });
        else setSettled({ key, status: "ready", data: body as T, refusal: null, error: null });
      } catch (e) {
        if (ctl.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
        setSettled({ key, status: "error", data: null, refusal: null, error: friendlyApiError(e, "Could not load this section") });
      }
    })();
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  const current = settled !== null && settled.key === key ? settled : null;
  return current ? { ...current, reload } : { status: "loading", data: null, refusal: null, error: null, reload };
}
