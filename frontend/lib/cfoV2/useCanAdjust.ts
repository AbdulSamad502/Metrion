"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

/** Whether this member may change CFO data (`financials.adjust`). Only decides which buttons to show — the server refuses the write regardless. Unknown reads as no. */
export function useCanAdjust(): boolean {
  const { getToken } = useAuth();
  const [can, setCan] = useState(false);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch<{ canAdjust: boolean }>("/api/v1/cfo/access", await getToken());
        if (alive) setCan(r.canAdjust === true);
      } catch {
        if (alive) setCan(false);
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return can;
}
