"use client";

import { useState } from "react";
import { Section } from "@/components/ui/Section";
import { apiFetch, type AnalyzeGstLinesResponse, type GstLookupResponse, type GstLookupResult, type GstPeriodSummaryResponse, type ManualAdjustmentIdResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { rupeesToPaise } from "@/lib/costInput";
import { CfoMetricResultRow, ComponentRowsEditor, EditableGstSummaryLine, ErrorText, Field, SelectInput, SubmitButton, TextInput, componentRowsToPayload, newGstSummaryLine, rupees, toPaise } from "@/components/cfo/primitives";

// --- 3. GST line analysis (POST /cfo/gst/analyze-lines) -----------------------------

type EditableGstLine = { line_ref: string; listed_rupees: string; basis: "INCLUSIVE" | "EXCLUSIVE"; rate_pct: string };

function newGstLine(): EditableGstLine {
  return { line_ref: "", listed_rupees: "", basis: "INCLUSIVE", rate_pct: "" };
}

export function GstLineAnalysisSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [lines, setLines] = useState<EditableGstLine[]>([newGstLine()]);
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeGstLinesResponse | null>(null);

  const update = (idx: number, patch: Partial<EditableGstLine>) =>
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  const remove = (idx: number) => setLines((ls) => ls.filter((_, i) => i !== idx));
  const add = () => setLines((ls) => [...ls, newGstLine()]);

  const submit = async () => {
    const validLines = lines.filter((l) => l.line_ref.trim() && l.listed_rupees.trim());
    if (validLines.length === 0 || !asOfDate) {
      setError("Add at least one line (with a ref and listed amount) and an as-of date first.");
      return;
    }
    for (const [i, l] of validLines.entries()) {
      if (rupeesToPaise(l.listed_rupees) === null) {
        setError(`Line ${i + 1} ("${l.line_ref.trim()}"): the listed amount must be a rupee amount like 1180 or 1,180.50. Nothing was sent.`);
        return;
      }
      if (l.rate_pct.trim() && !/^\d{1,3}(?:\.\d{1,4})?$/.test(l.rate_pct.trim())) {
        setError(`Line ${i + 1} ("${l.line_ref.trim()}"): the rate must be a plain number like 18 or 5.5, without a % sign. Nothing was sent.`);
        return;
      }
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        lines: validLines.map((l) => ({
          line_ref: l.line_ref.trim(),
          listed_paise: rupeesToPaise(l.listed_rupees),
          basis: l.basis,
          rate_pct: l.rate_pct.trim() || null,
        })),
        as_of_date: asOfDate,
      };
      const res = await apiFetch<AnalyzeGstLinesResponse>("/api/v1/cfo/gst/analyze-lines", await getToken(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not analyze GST lines"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="GST Line Analysis">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-2">
          {lines.map((line, idx) => (
            <div key={idx} className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              <TextInput value={line.line_ref} onChange={(v) => update(idx, { line_ref: v })} placeholder="line ref" />
              <TextInput value={line.listed_rupees} onChange={(v) => update(idx, { listed_rupees: v })} placeholder="listed ₹" />
              <SelectInput
                value={line.basis}
                onChange={(v) => update(idx, { basis: v as "INCLUSIVE" | "EXCLUSIVE" })}
                options={[
                  { value: "INCLUSIVE", label: "Inclusive" },
                  { value: "EXCLUSIVE", label: "Exclusive" },
                ]}
              />
              <TextInput value={line.rate_pct} onChange={(v) => update(idx, { rate_pct: v })} placeholder="rate % (optional)" />
              <button
                type="button"
                onClick={() => remove(idx)}
                className="rounded-lg px-3 py-2 t-body-sm font-semibold"
                style={{ border: "1px solid var(--border-default)", color: "var(--negative)" }}
              >
                Remove
              </button>
            </div>
          ))}
          <button type="button" onClick={add} className="w-fit t-meta font-semibold" style={{ color: "var(--text-3)" }}>
            + Add line
          </button>
        </div>
        <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Analyze lines" busyLabel="Analyzing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-1.5">
            {result.lines.map((l) => (
              <div
                key={l.lineRef}
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <div style={{ color: "var(--text-2)" }}><strong>{l.lineRef}</strong></div>
                {l.isAvailable ? (
                  <div style={{ color: "var(--text-3)" }}>
                    Normalized exclusive: {rupees(l.normalizedExclusivePaise)} · rate plausibility matched:{" "}
                    {l.ratePlausibilityMatched === null ? "—" : String(l.ratePlausibilityMatched)}
                    {l.ratePlausibilitySeverity && ` (${l.ratePlausibilitySeverity})`}
                  </div>
                ) : (
                  <div style={{ color: "var(--text-6)" }}>UNAVAILABLE{l.unavailableReason ? ` — ${l.unavailableReason}` : ""}</div>
                )}
                <div style={{ color: "var(--text-6)" }}>{l.disclaimer}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 4. GST period summary (POST /cfo/gst/period-summary) ---------------------------

export function GstPeriodSummarySection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [lines, setLines] = useState<EditableGstSummaryLine[]>([newGstSummaryLine()]);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GstPeriodSummaryResponse | null>(null);

  const updateLine = (idx: number, patch: Partial<EditableGstSummaryLine>) =>
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  const removeLine = (idx: number) => setLines((ls) => ls.filter((_, i) => i !== idx));
  const addLine = () => setLines((ls) => [...ls, newGstSummaryLine()]);
  const generateLineId = (idx: number) => updateLine(idx, { sales_line_id: crypto.randomUUID() });

  const submit = async () => {
    const validLines = lines.filter((l) => l.sales_line_id.trim() && l.marketplace.trim() && l.gross_item_amount_rupees.trim());
    if (validLines.length === 0 || !periodStart || !periodEnd || !asOfDate) {
      setError("Add at least one complete line and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        lines: validLines.map((l) => ({
          sales_line_id: l.sales_line_id.trim(),
          marketplace: l.marketplace.trim(),
          document_type: l.document_type.trim(),
          quantity: parseInt(l.quantity, 10) || 0,
          gross_item_amount_paise: toPaise(l.gross_item_amount_rupees),
          components: componentRowsToPayload(l.components),
          confidence: l.confidence.trim() || "CONFIRMED",
        })),
        period_start: periodStart,
        period_end: periodEnd,
        as_of_date: asOfDate,
      };
      const res = await apiFetch<GstPeriodSummaryResponse>("/api/v1/cfo/gst/period-summary", await getToken(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute the GST period summary"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="GST Period Summary">
      <div className="flex flex-col gap-4">
        {lines.map((line, idx) => (
          <div key={idx} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
              <div className="flex gap-2">
                <TextInput value={line.sales_line_id} onChange={(v) => updateLine(idx, { sales_line_id: v })} placeholder="sales_line_id (UUID)" />
                <button
                  type="button"
                  onClick={() => generateLineId(idx)}
                  className="rounded-lg px-2 py-2 t-micro font-semibold"
                  style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}
                >
                  Generate
                </button>
              </div>
              <TextInput value={line.marketplace} onChange={(v) => updateLine(idx, { marketplace: v })} placeholder="marketplace" />
              <TextInput value={line.document_type} onChange={(v) => updateLine(idx, { document_type: v })} placeholder="document_type" />
              <TextInput type="number" value={line.quantity} onChange={(v) => updateLine(idx, { quantity: v })} placeholder="quantity" />
            </div>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
              <TextInput
                value={line.gross_item_amount_rupees}
                onChange={(v) => updateLine(idx, { gross_item_amount_rupees: v })}
                placeholder="gross item amount ₹"
              />
              <TextInput value={line.confidence} onChange={(v) => updateLine(idx, { confidence: v })} placeholder="confidence (default CONFIRMED)" />
            </div>
            <div className="mt-2">
              <div className="mb-1 t-meta" style={{ color: "var(--text-6)" }}>Components</div>
              <ComponentRowsEditor rows={line.components} onChange={(rows) => updateLine(idx, { components: rows })} />
            </div>
            <button
              type="button"
              onClick={() => removeLine(idx)}
              className="mt-2 t-meta font-semibold"
              style={{ color: "var(--negative)" }}
            >
              Remove line
            </button>
          </div>
        ))}
        <button type="button" onClick={addLine} className="w-fit t-meta font-semibold" style={{ color: "var(--text-3)" }}>
          + Add line
        </button>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compute GST period summary" busyLabel="Computing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.results.map((r) => (
              <CfoMetricResultRow key={r.engineResultRef} label={r.metricCode} result={r} />
            ))}
            <div className="t-body-sm" style={{ color: "var(--text-6)" }}>{result.disclaimer}</div>
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 5. GST Applicability Lookup + Accept (POST /cfo/gst-lookup, /cfo/gst-lookup/accept) --

export function GstLookupSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [productTitle, setProductTitle] = useState("");
  const [sku, setSku] = useState("");
  const [hsn, setHsn] = useState("");
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GstLookupResponse | null>(null);

  const [acceptSku, setAcceptSku] = useState("");
  const [acceptReason, setAcceptReason] = useState("");
  const [acceptEffectiveFrom, setAcceptEffectiveFrom] = useState("");
  const [acceptBusy, setAcceptBusy] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [acceptResult, setAcceptResult] = useState<ManualAdjustmentIdResponse | null>(null);

  const lookup = async () => {
    if (!productTitle.trim()) {
      setError("Enter a product title first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    setAcceptResult(null);
    setAcceptError(null);
    try {
      const res = await apiFetch<GstLookupResponse>("/api/v1/cfo/gst-lookup", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          product_title: productTitle.trim(),
          sku: sku.trim() || null,
          hsn: hsn.trim() || null,
          category: category.trim() || null,
        }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not run the GST applicability lookup"));
    } finally {
      setBusy(false);
    }
  };

  const accept = async (lookupResult: GstLookupResult) => {
    if (!acceptSku.trim()) {
      setAcceptError("Enter the SKU to accept this rate for first.");
      return;
    }
    setAcceptBusy(true);
    setAcceptError(null);
    setAcceptResult(null);
    try {
      const res = await apiFetch<ManualAdjustmentIdResponse>("/api/v1/cfo/gst-lookup/accept", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          gst_lookup_result_id: lookupResult.id,
          sku: acceptSku.trim(),
          reason: acceptReason.trim() || null,
          effective_from: acceptEffectiveFrom || null,
        }),
      });
      setAcceptResult(res);
    } catch (e) {
      setAcceptError(friendlyApiError(e, "Could not accept this GST rate"));
    } finally {
      setAcceptBusy(false);
    }
  };

  return (
    <Section title="GST Applicability Lookup">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Product title"><TextInput value={productTitle} onChange={setProductTitle} placeholder="e.g. Cotton bedsheet set" /></Field>
          <Field label="SKU (optional)"><TextInput value={sku} onChange={setSku} /></Field>
          <Field label="HSN (optional)"><TextInput value={hsn} onChange={setHsn} /></Field>
          <Field label="Category (optional)"><TextInput value={category} onChange={setCategory} /></Field>
        </div>
        <div>
          <SubmitButton onClick={lookup} busy={busy} label="Look up GST rate" busyLabel="Looking up…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result?.noMatch && (
          <div className="t-body-sm" style={{ color: "var(--text-6)" }}>No match — {result.noMatch.reason}</div>
        )}
        {result?.result && (
          <div className="rounded-lg p-3 t-body-sm" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <div style={{ color: "var(--text-2)" }}>
              Likely rate: {result.result.likelyRatePct ?? "—"}% · HSN: {result.result.likelyHsn ?? "—"} · category:{" "}
              {result.result.likelyCategory ?? "—"}
            </div>
            {result.result.sourceUrl && <div style={{ color: "var(--text-5)" }}>Source: {result.result.sourceUrl}</div>}
            {result.result.ambiguityNote && <div style={{ color: "var(--negative)" }}>{result.result.ambiguityNote}</div>}
            <div style={{ color: "var(--text-6)" }}>{result.result.disclaimer}</div>
            {result.result.alternatives.length > 0 && (
              <ul className="ml-4 list-disc" style={{ color: "var(--text-5)" }}>
                {result.result.alternatives.map((a, i) => (
                  <li key={i}>{a.ratePct ?? "—"}% · {a.hsn ?? "—"} · {a.category ?? "—"}</li>
                ))}
              </ul>
            )}
            <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border-subtle)" }}>
              <div className="mb-2 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>Accept this rate for a SKU</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                <TextInput value={acceptSku} onChange={setAcceptSku} placeholder="SKU" />
                <TextInput value={acceptReason} onChange={setAcceptReason} placeholder="reason (optional)" />
                <TextInput type="date" value={acceptEffectiveFrom} onChange={setAcceptEffectiveFrom} />
              </div>
              <div className="mt-2">
                <SubmitButton
                  onClick={() => accept(result.result as GstLookupResult)}
                  busy={acceptBusy}
                  label="Accept rate"
                  busyLabel="Accepting…"
                />
              </div>
              <ErrorText>{acceptError}</ErrorText>
              {acceptResult && (
                <div className="mt-1" style={{ color: "var(--accent)" }}>
                  Accepted — manual adjustment <code>{acceptResult.manualAdjustmentId.slice(0, 8)}</code>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}
