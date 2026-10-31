"use client";

import { useRef, useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { performanceError, type ImportPreview, type ImportRow, type PerformanceApi } from "@/lib/cmoPerformance";

/** Import a marketplace performance report (CSV or Excel). Two steps: Preview shows exactly what would be saved and every problem; Import saves only what was previewed. Rows are only added; the same file
 * or an existing record is never imported twice and never overwritten; a blank cell stays blank. This is a manual import: Metrion has no live connection to any marketplace. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--ov-line)" };

export function ImportPanel({ api, imports, onImported }: { api: PerformanceApi; imports: ImportRow[]; onImported: () => void }) {
  const [marketplace, setMarketplace] = useState("AMAZON");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const check = async () => {
    if (!file || busy) return;
    setBusy(true); setMessage(null); setPreview(null);
    try { setPreview(await api.previewImport(file, marketplace)); } catch (e) { setMessage({ tone: "bad", text: performanceError(e).message }); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!file || !preview || busy) return;
    setBusy(true); setMessage(null);
    try {
      const r = await api.importReport(file, marketplace, preview.sha256);
      setMessage({ tone: "ok", text: r.message }); setPreview(null); setFile(null);
      if (input.current) input.current.value = "";
      onImported();
    } catch (e) { setMessage({ tone: "bad", text: performanceError(e).message }); } finally { setBusy(false); }
  };

  return (
    <SectionCard title="Import a performance report" hint="Upload a CSV or Excel report you downloaded from your marketplace seller account. Nothing is saved until you press Import.">
      <details className="mb-3 t-meta" style={{ color: "var(--ov-ink-2)" }}>
        <summary className="mt-focus font-bold" style={{ cursor: "pointer" }}>Which columns does the report need?</summary>
        <p className="m-0 mt-1">A <strong>Date</strong> column and a <strong>SKU</strong> column, and at least one of <strong>Impressions</strong>, <strong>Clicks</strong>, <strong>Orders</strong>, <strong>Units Sold</strong> or <strong>Sales</strong>.
          Dates as YYYY-MM-DD or DD/MM/YYYY. A blank cell, “-” or “N/A” is kept as missing, never as zero. CTR and conversion rate columns are not stored: they are worked out from your counts. Page views are not treated as impressions.
          If your marketplace report uses other column names, rename the headers to these before importing.</p>
      </details>
      <div className="flex flex-wrap items-end gap-3 t-meta">
        <label className="flex flex-col gap-1">Report is from
          <select aria-label="Report marketplace" className="mt-focus rounded-md px-2 py-1.5" style={box} value={marketplace} onChange={(e) => { setMarketplace(e.target.value); setPreview(null); }}>
            {Object.entries(MP).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">Report file
          <input ref={input} aria-label="Report file" type="file" accept=".csv,.xlsx" className="mt-focus" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); setMessage(null); }} />
        </label>
        <button type="button" disabled={!file || busy} className="mt-focus rounded-md px-3 py-1.5 font-bold" style={{ ...box, color: "var(--ov-brand-ink)" }} onClick={() => void check()}>{busy && !preview ? "Checking…" : "Preview"}</button>
      </div>
      <div role="status" aria-live="polite">{message && <p className="m-0 mt-2 t-body-sm" data-testid="import-message" style={{ color: "var(--ov-ink-2)" }}>{message.tone === "ok" ? "✓ " : "✗ "}{message.text}</p>}</div>

      {preview && (
        <div className="mt-3 flex flex-col gap-2 rounded-xl p-3" style={box} data-testid="import-preview">
          <strong className="t-body-sm" style={{ color: "var(--ov-ink)" }}>{preview.fileName} · {MP[preview.marketplace]}</strong>
          {preview.alreadyImported && <p className="m-0 t-meta" role="alert" style={{ color: "var(--ov-ink-2)" }}>✗ This exact file was already imported on {preview.alreadyImported.importedAt.slice(0, 10)}. Importing it again is not possible.</p>}
          {!preview.ok && (
            <div role="alert" data-testid="import-errors">
              <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>✗ {preview.errorCount} problem{preview.errorCount === 1 ? "" : "s"} in the file. Nothing can be saved until they are fixed.</p>
              <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>{preview.errors.map((e) => <li key={`${e.row}-${e.message}`}>{e.message}</li>)}</ul>
              {preview.errorCount > preview.errors.length && <p className="m-0 t-meta" style={{ color: "var(--ov-ink-3)" }}>…and {preview.errorCount - preview.errors.length} more.</p>}
            </div>
          )}
          {preview.ok && preview.period && (
            <>
              <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>
                Reporting period {preview.period.start} to {preview.period.end} ({preview.period.days} days). Metrics found: {preview.metrics.join(", ")}.
                {" "}{preview.newRows} new row{preview.newRows === 1 ? "" : "s"} to save{preview.duplicateRows ? `, ${preview.duplicateRows} already saved (skipped)` : ""}.
              </p>
              {preview.ignoredColumns.length > 0 && <p className="m-0 t-meta" style={{ color: "var(--ov-ink-3)" }}>Columns not used: {preview.ignoredColumns.join(", ")}.</p>}
              {preview.conflictCount ? (
                <div role="alert" data-testid="import-conflicts"><p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>✗ {preview.conflictCount} row(s) are already saved with different numbers. Existing records are never overwritten.</p>
                  <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>{preview.conflicts.map((c) => <li key={c.message}>{c.message}</li>)}</ul></div>
              ) : null}
              {preview.sample.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table className="t-meta" style={{ borderCollapse: "collapse" }} data-testid="import-sample">
                    <caption className="sr-only">The first rows that would be saved. A dash is a missing value.</caption>
                    <thead><tr>{Object.keys(preview.sample[0]).map((h) => <th key={h} scope="col" className="p-1 text-left">{h}</th>)}</tr></thead>
                    <tbody>{preview.sample.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j} className="p-1">{v}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              )}
            </>
          )}
          {preview.warnings.length > 0 && <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-3)" }} aria-label="Notes">{preview.warnings.map((w) => <li key={w}>○ {w}</li>)}</ul>}
          <div><button type="button" disabled={!preview.canImport || busy} className="mt-focus rounded-md px-3 py-1.5 font-bold" style={{ ...box, color: preview.canImport ? "var(--ov-brand-ink)" : "var(--ov-ink-3)" }} onClick={() => void save()}>{busy ? "Importing…" : "Import these rows"}</button></div>
        </div>
      )}

      <h3 className="m-0 mt-4 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>Imported reports</h3>
      {imports.length === 0 ? (
        <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-imports">No report imported yet. Until you import one, every metric stays unavailable; nothing is estimated.</p>
      ) : (
        <ul className="m-0 mt-1 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="import-list">
          {imports.map((i) => <li key={i.id}>{i.sourceName} · {MP[i.marketplace]} · {i.periodStart} to {i.periodEnd} · {i.rowsSaved} row{i.rowsSaved === 1 ? "" : "s"} · imported {i.importedAt.slice(0, 10)}</li>)}
        </ul>
      )}
    </SectionCard>
  );
}
