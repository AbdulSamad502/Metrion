"use client";

import { Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { flowSteps, routeLabel, routeSourceLabel } from "@/lib/ceoModel";
import type { FlowState } from "@/lib/useCeoHub";

/** "Show flow": how one turn was answered, read from the audit rows. It lists what ran and what was refused (and why), so a seller can see
 * that the CEO only used what was wired in and permitted. Display only; nothing here changes anything. */
export function FlowView({ flow }: { flow: FlowState }) {
  if (flow.status === "loading") {
    return (
      <div className="flex items-center gap-2 t-meta" style={{ color: "var(--text-5)" }} role="status">
        <Spinner size={12} /> Loading the flow…
      </div>
    );
  }
  if (flow.status === "error" || !flow.data) {
    return (
      <div className="t-meta" role="alert" style={{ color: "var(--negative)" }}>
        {flow.error ?? "Could not load the flow."}
      </div>
    );
  }
  const d = flow.data;
  const steps = flowSteps(d);
  return (
    <div className="flex flex-col gap-1.5 rounded-lg px-3 py-2.5" style={{ background: "var(--fill-hover)" }} data-testid="flow-view">
      <div className="t-meta font-semibold" style={{ color: "var(--text-2)" }}>
        {routeLabel(d.route)}
        {d.routeKey ? ` · ${d.routeKey}` : ""}
      </div>
      <div className="t-meta" style={{ color: "var(--text-5)" }}>
        {routeSourceLabel(d.routeSource)}
      </div>
      {steps.length === 0 ? (
        <div className="t-meta" style={{ color: "var(--text-5)" }}>
          No specialist ran for this turn.
        </div>
      ) : (
        <ol className="m-0 flex list-none flex-col gap-1 p-0">
          {steps.map((s) => (
            <li key={s.key} className="flex flex-wrap items-baseline gap-x-2 t-meta" style={{ color: "var(--text-4)" }}>
              <span className="font-semibold" style={{ color: "var(--text-2)" }}>
                {s.title}
              </span>
              <StatusBadge tone={s.status === "Completed" ? "accent" : s.status === "Partial" ? "warning" : s.status === "Running" || s.status === "Queued" ? "neutral" : "negative"}>
                {s.status}
              </StatusBadge>
              {s.detail && <span>{s.detail}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
