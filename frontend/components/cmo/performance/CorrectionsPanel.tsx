"use client";

import { useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { formatMetric, METRIC_LABEL, performanceError, type CorrectionRow, type MetricVals, type PerfLine, type PerformanceApi } from "@/lib/cmoPerformance";

/** Correcting a wrongly imported record (CMO 3.0 additional capability, M8 design 6c). The imported value is never changed: a correction is a new, permanent record with a reason, and the numbers use the
 * corrected value. Each record shows the imported value beside the effective one; a blank stays blank (not reported), never zero. A record corrected by someone else since it was opened is refused. */

const KEYS = ["impressions", "clicks", "orders", "units", "sales"] as const;
type Key = (typeof KEYS)[number];
const box: React.CSSProperties = { border: "1px solid var(--ov-line)" };
const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const show = (k: Key, v: number | null) => (v === null ? "not reported" : formatMetric(k, v));
const input = (k: Key, v: number | null) => (v === null ? "" : k === "sales" ? `${Math.floor(v / 100)}.${String(v % 100).padStart(2, "0")}` : String(v));

function Values({ vals, label }: { vals: MetricVals; label: string }) {
  return <span><strong>{label}:</strong> {KEYS.map((k) => `${METRIC_LABEL[k]} ${show(k, vals[k])}`).join(" · ")}</span>;
}

function Editor({ api, line, onSaved, onClose }: { api: PerformanceApi; line: PerfLine; onSaved: (m: string) => void; onClose: () => void }) {
  const start = Object.fromEntries(KEYS.map((k) => [k, input(k, line.effective[k])])) as Record<Key, string>;
  const [vals, setVals] = useState<Record<Key, string>>(start);
  const [reason, setReason] = useState("");
  const [voided, setVoided] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changes = Object.fromEntries(KEYS.filter((k) => vals[k] !== start[k]).map((k) => [k, vals[k].trim() === "" ? null : vals[k].trim()]));
  const nothing = !voided && Object.keys(changes).length === 0;
  const save = () => {
    setBusy(true);
    setError(null);
    api.correct({ lineId: line.lineId, changes: voided ? {} : changes, void: voided, reason, expectedCorrectionId: line.correctionId }).then(
      (r) => { setBusy(false); onSaved(r.message); },
      (e) => { setBusy(false); setError(performanceError(e).message); },
    );
  };
  return (
    <form className="mt-2 flex flex-col gap-2 rounded-lg p-3 t-meta" style={box} aria-label="Correct this record" data-testid="correction-form" onSubmit={(e) => { e.preventDefault(); if (!busy && !nothing && reason.trim().length >= 3) save(); }}>
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
        {KEYS.map((k) => (
          <label key={k} className="flex flex-col gap-1">{METRIC_LABEL[k]}{k === "sales" ? " (₹)" : ""}
            <input aria-label={METRIC_LABEL[k]} className="mt-focus rounded-md px-2 py-1" style={box} value={vals[k]} disabled={voided || busy} inputMode="decimal" onChange={(e) => setVals({ ...vals, [k]: e.target.value })} placeholder="not reported" />
          </label>
        ))}
      </div>
      <label className="flex items-center gap-2"><input type="checkbox" checked={voided} onChange={(e) => setVoided(e.target.checked)} disabled={busy} /> This record is wrong as a whole: mark every value “not reported”</label>
      <label className="flex flex-col gap-1">Why are you correcting it? (required)
        <textarea aria-label="Reason" className="mt-focus rounded-md px-2 py-1" style={box} rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
      </label>
      <p className="m-0 t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>The imported value is kept for good and shown beside the corrected one. A blank is saved as “not reported”, never as zero.</p>
      {error && <p role="alert" className="m-0" style={{ color: "var(--ov-bad)" }}>{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy || nothing || reason.trim().length < 3} className="mt-focus rounded-md px-3 py-1.5 font-bold" style={{ border: "1px solid var(--ov-brand-ink)", color: "var(--ov-brand-ink)", background: "transparent" }}>{busy ? "Saving…" : "Save correction"}</button>
        <button type="button" onClick={onClose} disabled={busy} className="mt-focus rounded-md px-3 py-1.5 font-bold" style={box}>Cancel</button>
      </div>
    </form>
  );
}

function Line({ api, line, onChanged }: { api: PerformanceApi; line: PerfLine; onChanged: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="flex flex-col gap-1 rounded-lg p-3 t-meta" style={box} data-testid="perf-line" data-corrected={line.corrected ? "yes" : "no"}>
      <div className="flex flex-wrap items-center gap-2">
        <strong style={{ color: "var(--ov-ink)" }}>{line.date} · {line.reportSku}</strong>
        <span style={{ color: "var(--ov-ink-3)" }}>from {line.sourceName}</span>
        {line.corrected && <span className="rounded-md px-1.5 py-0.5 font-bold" style={box} data-testid="corrected-badge">{line.voided ? "✗ VOIDED" : "✎ CORRECTED"}</span>}
      </div>
      <Values vals={line.original} label="Imported" />
      {line.corrected && <Values vals={line.effective} label="Used in your numbers" />}
      {!open && <button type="button" className="mt-focus self-start rounded-md px-2 py-1 font-bold" style={box} onClick={() => setOpen(true)}>{line.corrected ? "Correct again" : "Correct this record"}</button>}
      {open && <Editor api={api} line={line} onClose={() => setOpen(false)} onSaved={(m) => { setOpen(false); onChanged(m); }} />}
    </li>
  );
}

function History({ rows }: { rows: CorrectionRow[] }) {
  if (rows.length === 0) return <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-corrections">No corrections yet.</p>;
  return (
    <ol className="m-0 flex list-none flex-col gap-1.5 p-0 t-meta" style={{ color: "var(--ov-ink-2)" }} aria-label="Correction history">
      {rows.map((c) => (
        <li key={c.id} data-testid="correction-row">
          <strong>{c.at.slice(0, 10)}</strong> · {MP[c.marketplace]} · {c.reportSku} · {c.date} · {c.voided ? "marked not reported" : `changed ${c.changed.map((k) => METRIC_LABEL[k as Key] ?? k).join(", ")}`}<br />
          <Values vals={c.previous} label="Before" /><br /><Values vals={c.corrected} label="After" /><br />Reason: {c.reason}
        </li>
      ))}
    </ol>
  );
}

export function CorrectionsPanel({ api, version, onChanged }: { api: PerformanceApi; version: number; onChanged: () => void }) {
  const [mp, setMp] = useState("AMAZON");
  const [sku, setSku] = useState("");
  const [applied, setApplied] = useState({ mp: "AMAZON", sku: "" });
  const [offset, setOffset] = useState(0);
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const key = `${applied.mp}|${applied.sku}|${offset}#${tick}#${version}`;
  const { data, error } = useLoad(() => api.lines({ marketplace: applied.mp, reportSku: applied.sku || null, offset }), key);
  const { data: hist } = useLoad(() => api.correctionHistory({ marketplace: applied.mp, reportSku: applied.sku || null }), `h|${key}`);
  return (
    <SectionCard title="Correct an imported record" hint="Found a wrong number in an imported report? Correct it here. The imported value is kept, the correction is recorded with your reason, and your numbers use the corrected value.">
      <form className="mb-3 flex flex-wrap items-end gap-3 t-meta" aria-label="Find records" onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied({ mp, sku: sku.trim() }); }}>
        <label className="flex flex-col gap-1">Records marketplace
          <select aria-label="Records marketplace" className="mt-focus rounded-md px-2 py-1.5" style={box} value={mp} onChange={(e) => setMp(e.target.value)}>{Object.entries(MP).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label className="flex flex-col gap-1">Report SKU (optional)
          <input aria-label="Report SKU" className="mt-focus rounded-md px-2 py-1.5" style={box} value={sku} onChange={(e) => setSku(e.target.value)} />
        </label>
        <button type="submit" className="mt-focus rounded-md px-3 py-1.5 font-bold" style={box}>Show records</button>
      </form>
      {notice && <p role="status" className="m-0 mb-2 t-meta" style={{ color: "var(--ov-good)" }} data-testid="correction-saved">✓ {notice}</p>}
      {error && <p role="alert" className="m-0 t-body-sm">{error}</p>}
      {data && (
        <>
          <p className="m-0 mb-2 t-meta" style={{ color: "var(--ov-ink-2)" }}>{data.total} imported record(s) between {data.start} and {data.end} (newest first). {data.note}</p>
          {data.lines.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-lines">No imported records for this selection.</p> : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Imported records">{data.lines.map((l) => <Line key={l.lineId} api={api} line={l} onChanged={(m) => { setNotice(m); setTick((n) => n + 1); onChanged(); }} />)}</ul>
          )}
          <div className="mt-2 flex gap-2 t-meta">
            <button type="button" className="mt-focus rounded-md px-2 py-1 font-bold" style={box} disabled={data.offset === 0} onClick={() => setOffset(Math.max(0, data.offset - data.limit))}>← Newer</button>
            <button type="button" className="mt-focus rounded-md px-2 py-1 font-bold" style={box} disabled={!data.hasMore} onClick={() => setOffset(data.offset + data.limit)}>Older →</button>
          </div>
        </>
      )}
      <h3 className="m-0 mb-1 mt-4 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>Corrections you made</h3>
      {hist ? <History rows={hist.corrections} /> : <p className="m-0 t-meta" style={{ color: "var(--ov-ink-3)" }}>Loading…</p>}
    </SectionCard>
  );
}
