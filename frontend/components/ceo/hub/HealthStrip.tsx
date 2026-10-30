"use client";

import { PresentationView } from "@/components/ceo/hub/PresentationView";
import { Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { actionLabel, asOfLabel } from "@/lib/ceoModel";
import type { HealthState } from "@/lib/useCeoHub";

/** The business at a glance: CFO's GOOD / WATCH / AT-RISK bands and the latest saved profit & loss, straight from persisted results.
 * There is no composite score and no projection here by design (CP1-U1): each tile is one saved result with its own date, and a result that
 * is missing says so instead of showing a number. Nothing on this strip is computed in the browser. */
export function HealthStrip({ health, onRefresh, refreshing = false }: { health: HealthState; onRefresh: () => void; refreshing?: boolean }) {
  if (health.status === "loading" && health.entries.length === 0) {
    return (
      <p className="t-body-sm" style={{ color: "var(--text-5)" }} data-testid="health-loading">
        Loading your saved results…
      </p>
    );
  }
  if (health.entries.length === 0 && health.status === "ready") {
    // The request worked and there is simply nothing saved yet: that is not a failure, so no "unavailable" wording and no retry.
    return (
      <p className="t-body-sm" style={{ color: "var(--text-5)" }} data-testid="health-none-saved">
        No saved results yet. They appear here after you upload your reports in Profit &amp; Finance.
      </p>
    );
  }
  if (health.entries.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-3 t-body-sm" style={{ color: "var(--text-5)" }} data-testid="health-unavailable">
        Your saved results are not available to show here.
        <button type="button" onClick={onRefresh} disabled={refreshing} className="mt-btn mt-focus min-h-[36px] rounded-lg px-3 py-1 t-meta font-bold sm:min-h-0 sm:px-2.5" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
          {refreshing ? (
            <span className="inline-flex items-center gap-2">
              <Spinner size={12} /> Trying again…
            </span>
          ) : (
            "Try again"
          )}
        </button>
      </div>
    );
  }
  return (
    <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 md:grid-cols-2" aria-label="Business health" data-testid="health-strip">
      {health.entries.map((e) => {
        const p = e.presentation;
        const complete = e.status === "COMPLETE";
        const asOf = asOfLabel(e.asOf);
        return (
          <li key={e.key} data-testid={`health-${e.key}`} data-status={e.status} className="mt-panel rounded-xl px-4 py-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="t-body font-semibold" style={{ color: "var(--text-1)" }}>
                {actionLabel(e.key)}
              </span>
              {!complete && <StatusBadge tone="neutral">{e.status === "UNAVAILABLE" ? "Not available yet" : e.status.toLowerCase().replace(/_/g, " ")}</StatusBadge>}
              {e.period && <span className="t-meta" style={{ color: "var(--text-5)" }}>{e.period}</span>}
              {asOf && <span className="t-meta" style={{ color: "var(--text-5)" }}>{asOf}</span>}
            </div>
            {p ? (
              <PresentationView presentation={p} compact />
            ) : (
              <p className="t-body-sm" style={{ color: "var(--text-5)" }}>
                {e.previewHint ?? "Nothing saved to show yet."}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
