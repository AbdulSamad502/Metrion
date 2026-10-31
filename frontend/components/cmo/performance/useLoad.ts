"use client";

import { useEffect, useRef, useState } from "react";
import { performanceError } from "@/lib/cmoPerformance";

/** Loads one thing for a key. State is only set when the reply arrives, a reply for an older key is dropped, and a new key shows "loading" (`data` null) while `last` keeps the previous result for
 * things such as the options of a filter. */
export function useLoad<T>(load: () => Promise<T>, key: string): { data: T | null; last: T | null; error: string | null; loading: boolean } {
  const [done, setDone] = useState<{ key: string; data: T | null; error: string | null } | null>(null);
  const [last, setLast] = useState<T | null>(null);
  const ref = useRef(load);
  useEffect(() => {
    ref.current = load;
  });
  useEffect(() => {
    let live = true;
    ref.current().then(
      (data) => {
        if (!live) return;
        setDone({ key, data, error: null });
        setLast(data);
      },
      (e) => live && setDone({ key, data: null, error: performanceError(e).message }),
    );
    return () => {
      live = false;
    };
  }, [key]);
  const same = done !== null && done.key === key;
  return { data: same ? done.data : null, last, error: same ? done.error : null, loading: !same };
}
