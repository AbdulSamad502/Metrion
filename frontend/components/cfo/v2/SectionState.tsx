"use client";

import type { ReactNode } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import type { DataState } from "@/lib/cfoV2/useCfoData";

/** One section's loading / error / refused states, so each card on the page loads, fails and explains itself independently of the others. */
export function SectionState<T>({ state, title, children }: { state: DataState<T>; title: string; children: (data: T) => ReactNode }) {
  if (state.status === "loading" && !state.data) return <LoadingState lines={2} label={`Loading ${title}`} />;
  if (state.status === "error") return <ErrorNotice message={state.error ?? "Could not load this section"} onRetry={state.reload} />;
  if (state.status === "refused") {
    return (
      <div role="status" className="rounded-lg p-3 t-body" style={{ background: "var(--fill-hover)" }}>
        {state.refusal?.message ?? "This could not be answered."}
      </div>
    );
  }
  return state.data ? <>{children(state.data)}</> : null;
}
