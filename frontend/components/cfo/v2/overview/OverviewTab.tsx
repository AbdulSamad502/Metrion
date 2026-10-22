"use client";

import Link from "next/link";
import { FilterBar } from "@/components/cfo/v2/filters/FilterBar";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { FigureView } from "@/components/cfo/v2/trust/FigureView";
import { periodQuery, type OverviewResponse, type Period } from "@/lib/cfoV2/dashboard";
import { useCfoData } from "@/lib/cfoV2/useCfoData";
import { useCfoFilters } from "@/lib/cfoV2/useCfoFilters";

const OP_STATE_TEXT: Record<string, string> = {
  PROVISIONAL: "Operating Profit is provisional: some expenses are still unclassified or on hold.",
  FINAL: "Operating Profit counts every classified expense in this period.",
  UNAVAILABLE: "Operating Profit needs your expenses first: upload an expense file or say you had none.",
};

/** Overview: six figures, each through `FigureView` with its source, completeness and what is missing. Nothing here is computed in the browser. */
export function OverviewTab({ period }: { period: Period }) {
  const [filters, setFilters] = useCfoFilters();
  const state = useCfoData<OverviewResponse>("/overview", periodQuery(filters, period));
  return (
    <div className="flex flex-col gap-6">
      <FilterBar filters={filters} onChange={setFilters} />
      <SectionState state={state} title="the overview">
        {(o) => (
          <>
            <p className="t-meta" style={{ color: "var(--text-5)" }}>
              Last updated {o.generatedAt}
              {o.cached ? " (from a saved answer for the same data)" : ""}
            </p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {o.kpis.map((k) => (
                <FigureView key={k.label} figure={k} />
              ))}
            </div>
            {o.operatingProfitState && <p className="t-body">{OP_STATE_TEXT[o.operatingProfitState]}</p>}
            {o.urgentActions.length > 0 && (
              <section aria-label="What needs your attention" className="flex flex-col gap-2">
                <h3 className="t-label">What needs your attention</h3>
                <ul className="list-disc pl-5 t-body">
                  {o.urgentActions.map((a) => (
                    <li key={a.text}>{a.text}</li>
                  ))}
                </ul>
              </section>
            )}
            {o.coverage.length > 0 && (
              <section aria-label="Coverage by marketplace" className="flex flex-col gap-2">
                <h3 className="t-label">How complete each marketplace is</h3>
                <ul className="list-disc pl-5 t-body">
                  {o.coverage.map((c) => (
                    <li key={`${c.metricId}-${c.marketplace}`}>
                      {c.marketplace} · {c.metricId.replaceAll("_", " ").toLowerCase()}:{" "}
                      {c.included ? `included (${c.sharePct ?? "—"}% of lines have the data)` : `left out${c.reason ? `: ${c.reason}` : ""}${c.excludedAmountDisplay ? ` · ${c.excludedAmountDisplay} of gross sales not counted` : ""}`}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <p className="t-meta">
              <Link href="/dashboard/ceo-hub" className="underline">
                Ask the CEO about these figures
              </Link>
            </p>
          </>
        )}
      </SectionState>
    </div>
  );
}
