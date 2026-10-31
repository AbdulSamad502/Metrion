"use client";

import { useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { ConfirmationsPanel } from "@/components/cmo/performance/ConfirmationsPanel";
import { ImportPanel } from "@/components/cmo/performance/ImportPanel";
import { TrendCharts } from "@/components/cmo/performance/TrendChart";
import { VersionPanel } from "@/components/cmo/performance/VersionPanel";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { METRIC_KEYS, METRIC_LABEL, describeChange, formatMetric, type Dashboard, type Insight, type MetricKey, type PerformanceApi } from "@/lib/cmoPerformance";

/** Listing performance (CMO 3.0 M8). Everything on this page comes from reports the seller imported themselves; nothing is estimated, no figure is shown for a period the reports do not fully cover, and
 * no difference is called an effect of a listing change. Reading it costs no AI credit. A figure that cannot be shown says NOT ASSESSED or UNAVAILABLE and why, never zero. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const when = (iso: string | null) => (iso ? iso.slice(0, 10) : "—");

function Card({ k, d }: { k: MetricKey; d: Dashboard }) {
  const m = d.current.metrics[k];
  const c = d.comparison[k];
  return (
    <li className="flex flex-col gap-1 rounded-xl p-3" style={box} data-testid={`metric-${k}`} data-state={m.state}>
      <span className="t-meta font-bold" style={{ color: "var(--text-3)" }}>{METRIC_LABEL[k]}</span>
      {m.state === "AVAILABLE" && m.value !== null ? (
        <strong className="t-heading" style={{ color: "var(--text-1)", fontSize: 24 }}>{formatMetric(k, m.value)}</strong>
      ) : (
        <strong className="t-body-sm" style={{ color: "var(--text-3)" }}>{m.state === "UNAVAILABLE" ? "UNAVAILABLE" : "NOT ASSESSED"}</strong>
      )}
      {m.state !== "AVAILABLE" && m.reason && <span className="t-meta" style={{ color: "var(--text-4)" }}>{m.reason}</span>}
      {m.state === "AVAILABLE" && <span className="t-meta" style={{ color: "var(--text-3)" }} data-testid={`change-${k}`}>{c.state === "AVAILABLE" ? describeChange(k, c) : `Previous period: not assessed. ${c.reason}`}</span>}
    </li>
  );
}

function InsightItem({ i }: { i: Insight }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl p-3" style={box} data-testid="insight" data-kind={i.kind}>
      <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>{i.what}</strong>
      {i.evidence.length > 0 && (
        <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-3)" }} aria-label="Supporting figures">
          {i.evidence.map((e) => <li key={e.metric}><strong>Measured:</strong> {e.label} {e.previous} → {e.current} ({e.previousPeriod} → {e.currentPeriod})</li>)}
        </ul>
      )}
      <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}><strong>Why it may matter (possible, not measured):</strong> {i.whyItMatters}</p>
      <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}><strong>Next step:</strong> {i.nextStep}{i.action ? ` Ask me: “${i.action.ask}”.` : ""}</p>
      <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-4)" }} aria-label="Limits">{i.limits.map((l) => <li key={l}>Limit: {l}</li>)}</ul>
    </li>
  );
}

export function PerformanceDashboard({ api }: { api: PerformanceApi }) {
  const [filters, setFilters] = useState<{ marketplace: string; sku: string; start: string; end: string }>({ marketplace: "", sku: "", start: "", end: "" });
  const [applied, setApplied] = useState(filters);
  const [tick, setTick] = useState(0);
  const { data: d, last, error } = useLoad(() => api.dashboard({ marketplace: applied.marketplace || null, sku: applied.sku || null, start: applied.start || null, end: applied.end || null }), `${JSON.stringify(applied)}#${tick}`);
  const refresh = () => setTick((n) => n + 1);

  return (
    <div className="flex flex-col gap-5" data-testid="performance-dashboard">
      <SectionCard title="Your listing performance" hint="From the performance reports you imported. Nothing here is estimated, and reading it uses no AI credit.">
        <form className="flex flex-wrap items-end gap-3 t-meta" aria-label="Filters" onSubmit={(e) => { e.preventDefault(); if (!!filters.start === !!filters.end) setApplied(filters); }}>
          <label className="flex flex-col gap-1">Marketplace
            <select aria-label="Marketplace" className="mt-focus rounded-md px-2 py-1.5" style={box} value={filters.marketplace} onChange={(e) => setFilters({ ...filters, marketplace: e.target.value })}>
              <option value="">All marketplaces</option>{Object.entries(MP).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">Product
            <select aria-label="Product" className="mt-focus rounded-md px-2 py-1.5" style={box} value={filters.sku} onChange={(e) => setFilters({ ...filters, sku: e.target.value })}>
              <option value="">All imported rows</option>{((d ?? last)?.products ?? []).map((p) => <option key={p.sku} value={p.sku}>{p.name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">From<input aria-label="From date" type="date" className="mt-focus rounded-md px-2 py-1.5" style={box} value={filters.start} max={filters.end || undefined} onChange={(e) => setFilters({ ...filters, start: e.target.value })} /></label>
          <label className="flex flex-col gap-1">To<input aria-label="To date" type="date" className="mt-focus rounded-md px-2 py-1.5" style={box} value={filters.end} min={filters.start || undefined} onChange={(e) => setFilters({ ...filters, end: e.target.value })} /></label>
          <button type="submit" className="mt-focus rounded-md px-3 py-1.5 font-bold" style={{ ...box, color: "var(--accent)" }}>Apply</button>
          {(filters.start || filters.end) && !(filters.start && filters.end) && <span role="alert" style={{ color: "var(--text-3)" }}>Choose both dates, or neither.</span>}
        </form>
        {error && <p role="alert" className="mt-3 t-body-sm" style={{ color: "var(--text-2)" }} data-testid="performance-error">{error}</p>}
        {!d && !error && <p className="mt-3 t-meta" role="status" style={{ color: "var(--text-4)" }}>Loading…</p>}
        {d && (
          <>
            <p className="mt-3 t-meta" style={{ color: "var(--text-3)" }} data-testid="data-coverage">
              Source: {d.source}. Period shown: {d.current.periodStart} to {d.current.periodEnd} ({d.current.coveredDays} of {d.current.days} days covered by imported reports).
              {" "}Last import: {when(d.dataSpan.lastImportAt)}. Your reports run from {when(d.dataSpan.first)} to {when(d.dataSpan.last)}.
            </p>
            {d.needs.length > 0 && <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-2)" }} data-testid="needs">To show this product I need {d.needs.join("; ")}.</p>}
            {d.limits.map((l) => <p key={l} className="m-0 mt-1 t-meta" style={{ color: "var(--text-3)" }}>○ {l}</p>)}
            <ul className="mt-3 grid list-none gap-3 p-0" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }} aria-label="Metrics for the period">
              {METRIC_KEYS.map((k) => <Card key={k} k={k} d={d} />)}
            </ul>
          </>
        )}
      </SectionCard>

      {d && (
        <SectionCard title="Trend over the period" hint="One chart per metric. A day with no value is a gap, never zero.">
          <TrendCharts points={d.trend} keys={["impressions", "clicks", "ctr", "orders", "cvr", "sales"]} />
        </SectionCard>
      )}

      {d && (
        <SectionCard title="What stands out" hint="Observations from the figures above. Possible explanations are labelled as possible; none is a finding about cause.">
          <ul className="m-0 flex list-none flex-col gap-3 p-0" data-testid="insights">{d.insights.map((i) => <InsightItem key={i.kind} i={i} />)}</ul>
          <p className="m-0 mt-3 t-meta" style={{ color: "var(--text-4)" }}>{d.never}</p>
        </SectionCard>
      )}

      <ImportPanel api={api} imports={d?.imports ?? []} onImported={refresh} />
      <ConfirmationsPanel api={api} onChanged={refresh} />
      <VersionPanel api={api} version={tick} />
    </div>
  );
}
