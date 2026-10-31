"use client";

import { useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { useLoad } from "@/components/cmo/performance/useLoad";
import Link from "next/link";
import { METRIC_KEYS, METRIC_LABEL, describeChange, formatMetric, handoffHref, type PerformanceApi, type VersionRow } from "@/lib/cmoPerformance";

/** What was observed in the same number of days before and after each saved version went live, using the go-live dates the seller confirmed. Observation only: a difference between two periods is never
 * presented as the effect of a listing change, and a version without a confirmed date, a SKU link, or full report coverage is NOT ASSESSED with the reason. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const STATE: Record<VersionRow["state"], string> = { OBSERVED_COMPARABLE: "✓ Compared", INCOMPARABLE: "✗ Cannot compare", NOT_ASSESSED: "○ Not assessed" };

function Row({ v, days }: { v: VersionRow; days: number | null }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl p-3" style={box} data-testid="version-row" data-state={v.state}>
      <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>Version {v.number} · {v.source}{v.changedSection ? ` (${v.changedSection.toLowerCase()})` : ""} · {STATE[v.state]}</strong>
      <span className="t-meta" style={{ color: "var(--text-3)" }}>Written {v.createdAt}. {v.wentLiveOn ? `You said it went live on ${v.wentLiveOn}.` : "No go-live date confirmed."}</span>
      {v.state === "NOT_ASSESSED" && v.needs.length > 0 && <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-2)" }} aria-label="Needed">{v.needs.map((n) => <li key={n}>✗ I need {n}.</li>)}</ul>}
      {v.state === "INCOMPARABLE" && <span className="t-meta" style={{ color: "var(--text-2)" }}>{v.note}</span>}
      {v.state === "OBSERVED_COMPARABLE" && v.comparison && v.previous && v.following && (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="t-meta" style={{ borderCollapse: "collapse", minWidth: 460 }} data-testid="version-table">
              <caption className="sr-only">{days} days before ({v.previous.periodStart} to {v.previous.periodEnd}) and {days} days after ({v.following.periodStart} to {v.following.periodEnd}) this version went live</caption>
              <thead><tr><th scope="col" className="p-1 text-left">Metric</th><th scope="col" className="p-1 text-right">Before</th><th scope="col" className="p-1 text-right">After</th><th scope="col" className="p-1 text-left">Difference</th></tr></thead>
              <tbody>
                {METRIC_KEYS.map((k) => {
                  const c = v.comparison![k];
                  return <tr key={k}><th scope="row" className="p-1 text-left font-normal">{METRIC_LABEL[k]}</th>
                    <td className="p-1 text-right">{c.state === "AVAILABLE" ? formatMetric(k, c.previous) : "Not assessed"}</td><td className="p-1 text-right">{c.state === "AVAILABLE" ? formatMetric(k, c.current) : "Not assessed"}</td>
                    <td className="p-1">{c.state === "AVAILABLE" ? describeChange(k, c).replace("from the previous period", "after") : c.reason}</td></tr>;
                })}
              </tbody>
            </table>
          </div>
          <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-3)" }} aria-label="Observations">{v.observations?.map((o) => <li key={o}>{o}</li>)}</ul>
          {v.insights?.filter((i) => i.measured).map((i) => <p key={i.kind} className="m-0 t-meta" style={{ color: "var(--text-3)" }}><strong>{i.what}</strong> <span style={{ color: "var(--text-4)" }}>Possible reason: {i.whyItMatters} Next step: {i.nextStep}</span>{i.action && handoffHref(i.action) && <> <Link href={handoffHref(i.action) as string} className="mt-focus font-bold" style={{ color: "var(--accent)" }} data-testid="handoff">{i.action.label} →</Link></>}</p>)}
          <span className="t-meta" style={{ color: "var(--text-4)" }}>{v.note}</span>
        </>
      )}
    </li>
  );
}

export function VersionPanel({ api, version }: { api: PerformanceApi; version: number }) {
  const [chosen, setChosen] = useState("");
  const { data: maps, error: mapsErr } = useLoad(() => api.mappings(), `maps#${version}`);
  const pick = chosen || (maps?.items[0] ? `${maps.items[0].sku}|${maps.items[0].marketplace}` : "");
  const { data, error: verErr } = useLoad(async () => { if (!pick) return null; const [sku, mp] = pick.split("|"); return api.versions(sku, mp); }, `${pick}#${version}`);
  const err = mapsErr ?? verErr;
  return (
    <SectionCard title="Before and after each listing version" hint="The same number of days before and after the date you confirmed a version went live. This shows what was observed, not what caused it.">
      {err && <p role="alert" className="m-0 t-body-sm">{err}</p>}
      {maps && maps.items.length === 0 && <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="no-versions">No saved listing yet.</p>}
      {maps && maps.items.length > 1 && (
        <label className="mb-2 flex flex-col gap-1 t-meta">Listing
          <select aria-label="Listing" className="mt-focus rounded-md px-2 py-1.5" style={box} value={pick} onChange={(e) => setChosen(e.target.value)}>{maps.items.map((i) => <option key={`${i.sku}|${i.marketplace}`} value={`${i.sku}|${i.marketplace}`}>{i.product} · {MP[i.marketplace]}</option>)}</select>
        </label>
      )}
      {data && (
        <>
          {data.needs.length > 0 && <ul className="m-0 mb-2 list-none p-0 t-meta" style={{ color: "var(--text-2)" }} data-testid="version-needs">{data.needs.map((n) => <li key={n}>✗ I need {n}.</li>)}</ul>}
          <ol className="m-0 flex list-none flex-col gap-3 p-0" aria-label="Versions, oldest first">{data.versions.map((v) => <Row key={v.versionId} v={v} days={data.windowDays} />)}</ol>
        </>
      )}
    </SectionCard>
  );
}
