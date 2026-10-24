"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useDemo } from "@/lib/demo/mode";
import { evidenceOf, explainPiError, formatPaise, imageDomain, safeHref, SOURCE_LABEL, type PiCase, type PiClient, type PiProduct } from "@/lib/piShowcase";

/** The print / Save-as-PDF layout of one saved Product Intelligence report (docs/specs/ceo-pi-research-flow.md C7). Black on white, no app chrome, nothing that starts research.
 * It shows exactly what the saved report holds: the five shortlisted products, the commentary findings, supplier leads, the CFO results the seller's own quote produced (or the
 * named reason they are missing), PI's recommendation and what the research could not provide. Every figure is stored by the backend and printed as it arrives. */

const ink = "#111";
const muted = "#555";
const rule = "#ccc";
const fmtDate = (iso: string | null | undefined) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" }) : "date not stated";
};
const score = (s: string | null) => (s ? `${s}/100` : "no score");

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-3 py-0.5" style={{ gridTemplateColumns: "9.5rem minmax(0, 1fr)" }}>
      <div style={{ color: muted, fontWeight: 600 }}>{label}</div>
      <div style={{ overflowWrap: "anywhere" }}>{children}</div>
    </div>
  );
}

function Product({ p, brief }: { p: PiProduct; brief: PiCase["brief"] }) {
  const c = p.candidate;
  const rec = p.recommendation;
  const lead = p.supplierLeads.find((l) => l.id === p.bestSupplierLeadId) ?? rec.supplier_option;
  const img = safeHref(c.image_url);
  const web = c.web_price_signal && c.web_price_signal.status !== "UNAVAILABLE" ? c.web_price_signal : null;
  const published = lead?.contact?.published_price ?? null;
  const band = brief.targetPriceMinPaise != null && brief.targetPriceMaxPaise != null ? `${formatPaise(brief.targetPriceMinPaise)} - ${formatPaise(brief.targetPriceMaxPaise)} (your target band)` : null;
  return (
    <section className="py-4" style={{ borderTop: `1px solid ${rule}`, breakInside: "avoid" }} aria-label={`Rank ${p.rank}: ${c.candidate_title}`}>
      <div className="flex gap-4">
        {img && (
          <div className="shrink-0" style={{ width: 120 }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- hotlinked from arbitrary hosts, attributed below (PI spec C8) */}
            <img src={img} alt={c.candidate_title} referrerPolicy="no-referrer" style={{ width: 120, height: 120, objectFit: "contain" }} />
            <div style={{ color: muted, fontSize: 10 }}>image from {imageDomain(c.image_source_url)}</div>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h3 style={{ fontSize: 16, fontWeight: 700 }}>#{p.rank} {c.candidate_title}</h3>
          <div style={{ color: muted }}>{c.observed_category ?? "Opportunity candidate"} · score {score(p.finalScore)} · opportunity candidate from public web signal, not a verified sales ranking</div>
          <div className="mt-2">
            <Row label="Research evidence">
              {(() => {
                const ev = evidenceOf(c);
                return (
                  <>
                    {ev.independentSources === null ? "Independent sources not recorded." : `${ev.independentSources} independent source(s).`}{" "}
                    {ev.sources.slice(0, 6).map((s) => `${s.domain} (${s.kind})`).join(", ")}
                    {ev.sources.length ? ". " : ""}
                    {ev.engagement ? `YouTube: ${ev.engagement.videos ?? "n/a"} video(s), ${ev.engagement.views?.toLocaleString("en-IN") ?? "n/a"} views, ${ev.engagement.comments?.toLocaleString("en-IN") ?? "n/a"} comments.` : `YouTube engagement unavailable (${ev.engagementMissing}).`}
                    {ev.demandMissing ? ` Search demand unavailable (${ev.demandMissing}).` : ""}
                  </>
                );
              })()}
            </Row>
            <Row label="Why it ranks here">{rec.why_ranked.length ? rec.why_ranked.join("; ") : "No ranking reasons were stored."}</Row>
            <Row label="Liked (commentary)">{rec.pros.length ? rec.pros.join(", ") : "No positive themes found."}</Row>
            <Row label="Watch out for">{rec.cons.length ? rec.cons.join(", ") : "No complaint themes found."}</Row>
            <Row label="Selling price">
              {band ?? "No target price was stated."}
              {web?.average_paise != null ? ` Web-mentioned reference ${formatPaise(web.average_paise)} (not verified).` : ""}
            </Row>
            <Row label="Supplier lead">
              {lead ? (
                <>
                  {lead.supplier_name}{lead.locality ? `, ${lead.locality}` : ""} · {SOURCE_LABEL[lead.source] ?? lead.source}
                  {lead.contact?.phone ? ` · ${lead.contact.phone}` : ""}
                  {lead.contact?.website ? ` · ${lead.contact.website}` : lead.source_url ? ` · ${lead.source_url}` : ""}
                  {published ? ` · Published price ${published.low_paise === published.high_paise ? formatPaise(published.low_paise) : `${formatPaise(published.low_paise)} - ${formatPaise(published.high_paise)}`} per ${published.unit} (the supplier's own page, ${fmtDate(published.captured_at)}; not a quote)` : ""}
                </>
              ) : (
                "No supplier lead was found."
              )}
            </Row>
            <Row label="CFO results">
              {p.financials.length === 0 ? (
                "Not calculated: they need a supplier quote you confirm with the CEO."
              ) : (
                <ul>
                  {p.financials.map((f) => (
                    <li key={`${f.leg_key}-${f.label}`}>{f.label}: {f.display ?? `Unavailable${f.reason ? ` (${f.reason})` : ""}`}{f.display ? " (from your confirmed supplier quote)" : ""}</li>
                  ))}
                </ul>
              )}
            </Row>
            {rec.gaps.length > 0 && <Row label="Missing evidence">{rec.gaps.join("; ")}</Row>}
          </div>
        </div>
      </div>
    </section>
  );
}

export function PiReportPrint({ client, runId }: { client: PiClient; runId: string }) {
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: PiCase }>({ status: "loading" });
  useEffect(() => {
    let live = true;
    client.report(runId).then(
      (data) => { if (live) setState({ status: "ready", data }); },
      (e) => { if (live) setState({ status: "error", message: explainPiError(e).message }); },
    );
    return () => { live = false; };
  }, [client, runId]);

  return (
    <div style={{ background: "#fff", color: ink, minHeight: "100vh", fontSize: 12, lineHeight: 1.45 }}>
      <style>{"@page { margin: 14mm; } @media print { html:root { background: #fff !important; color-scheme: light !important; } .pi-no-print { display: none !important; } }"}</style>
      <main className="mx-auto max-w-[800px] px-6 py-6">
        {state.status === "loading" && <p role="status">Loading the saved report…</p>}
        {state.status === "error" && <p role="alert">{state.message}</p>}
        {state.status === "ready" && <Body c={state.data} />}
      </main>
    </div>
  );
}

function Body({ c }: { c: PiCase }) {
  const b = c.brief;
  const sample = useDemo(); // sample-data preview (dev/preview builds only): the report is made up, and the paper copy must say so
  return (
    <>
      {sample && (
        <p role="note" className="mb-2 font-bold" style={{ border: `2px solid ${ink}`, padding: "4px 8px" }}>
          SAMPLE DATA: this report is fictional and is not a real research result.
        </p>
      )}
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3" style={{ borderBottom: `2px solid ${ink}`, paddingBottom: 8 }}>
        <div>
          <div style={{ fontSize: 10, letterSpacing: 1, color: muted, fontWeight: 700 }}>METRION · PRODUCT INTELLIGENCE REPORT</div>
          <h1 style={{ fontSize: 20, fontWeight: 800 }}>{b.category ?? "Saved research"}</h1>
          <div style={{ color: muted }}>
            {b.budgetPaise != null ? `Budget ${formatPaise(b.budgetPaise)} · ` : ""}
            {b.targetPriceMinPaise != null && b.targetPriceMaxPaise != null ? `Target price ${formatPaise(b.targetPriceMinPaise)} - ${formatPaise(b.targetPriceMaxPaise)} · ` : ""}
            {b.marketplaces?.length ? `${b.marketplaces.map((m) => m[0] + m.slice(1).toLowerCase()).join(", ")} · ` : ""}saved {fmtDate(c.completedAt)}{c.status === "PARTIAL" ? " · partial run" : ""}
          </div>
          <div style={{ color: muted, fontSize: 10 }}>Report {c.runId}</div>
        </div>
        <button type="button" onClick={() => window.print()} className="pi-no-print rounded px-3 py-1.5 font-bold" style={{ background: ink, color: "#fff" }}>
          Print / Save as PDF
        </button>
      </header>

      {c.overall && (
        <p className="mb-2"><strong>Strongest opportunity: {c.overall.title}</strong> - {c.overall.reason}.</p>
      )}
      {c.products.length === 0 ? <p>This report has no shortlisted products{c.gaps.length ? `: ${c.gaps.join("; ")}` : ""}.</p> : c.products.map((p) => <Product key={p.candidate.id} p={p} brief={b} />)}

      <section className="mt-3 pt-3" style={{ borderTop: `1px solid ${rule}`, breakInside: "avoid" }}>
        <h2 style={{ fontSize: 13, fontWeight: 700 }}>What this research could not provide</h2>
        <ul className="list-disc pl-5">
          {c.unavailable.map((u) => <li key={u.field}><strong>{u.field.replace(/_/g, " ")}:</strong> {u.reason}</li>)}
          {c.gaps.map((g) => <li key={g}>{g}</li>)}
        </ul>
        <p className="mt-2" style={{ color: muted }}>
          Opportunity candidates come from public web and video signal; they are not verified as selling well and are not sales data. Commentary is viewer and web commentary, not verified marketplace buyer reviews.
          Supplier details are leads as published by their sources and are not checked by Metrion. Cost, margin and units appear only from a supplier quote the seller confirmed. These are estimates, not a purchase instruction.
        </p>
      </section>
    </>
  );
}
