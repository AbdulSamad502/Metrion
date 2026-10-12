"use client";

import { useState } from "react";
import { Section } from "@/components/ui/Section";
import { CostInput } from "@/components/ui/CostInput";
import { costReady, costToApi, EMPTY_COST, type CostChoice } from "@/lib/costInput";
import { apiFetch, type BatchSizeResponse, type FundingReadinessResponse, type LandedCostResponse, type PricingCurveResponse, type SupplierRankingResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { DataRequestNote } from "@/components/cfo/DataRequestNote";
import { CfoMetricResultRow, ComponentRowsEditor, EditableGstSummaryLine, ErrorText, Field, SelectInput, SubmitButton, TextInput, componentRowsToPayload, newGstSummaryLine, toPaise } from "@/components/cfo/primitives";

// --- 6. Pricing curve (POST /cfo/pricing) --------------------------------------------

export function PricingCurveSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [sku, setSku] = useState("");
  const [candidatePrices, setCandidatePrices] = useState<string[]>([""]);
  const [basis, setBasis] = useState<"INCLUSIVE" | "EXCLUSIVE">("INCLUSIVE");
  const [gstRatePct, setGstRatePct] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [category, setCategory] = useState("");
  const [feeType, setFeeType] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [cogsUnavailable, setCogsUnavailable] = useState(false);
  const [cogsRupees, setCogsRupees] = useState("");
  const [cogsUnavailableReason, setCogsUnavailableReason] = useState("");
  const [shipping, setShipping] = useState<CostChoice>(EMPTY_COST);
  const [advertising, setAdvertising] = useState<CostChoice>(EMPTY_COST);
  const [other, setOther] = useState<CostChoice>(EMPTY_COST);
  const [rtoUnavailable, setRtoUnavailable] = useState(false);
  const [rtoRupees, setRtoRupees] = useState("");
  const [rtoUnavailableReason, setRtoUnavailableReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PricingCurveResponse | null>(null);

  const updatePrice = (idx: number, v: string) => setCandidatePrices((ps) => ps.map((p, i) => (i === idx ? v : p)));
  const removePrice = (idx: number) => setCandidatePrices((ps) => ps.filter((_, i) => i !== idx));
  const addPrice = () => setCandidatePrices((ps) => [...ps, ""]);

  const submit = async () => {
    const validPrices = candidatePrices.filter((p) => p.trim());
    if (!sku.trim() || validPrices.length === 0 || !marketplace.trim() || !category.trim() || !feeType.trim() || !asOfDate) {
      setError("Fill in SKU, at least one candidate price, marketplace, category, fee type and as-of date first.");
      return;
    }
    if (![shipping, advertising, other].every(costReady)) {
      setError("Answer shipping, advertising and other costs: an amount, \"None (0), I confirm\", or Unknown. Nothing is assumed to be zero.");
      return;
    }
    const ship = costToApi(shipping);
    const ads = costToApi(advertising);
    const oth = costToApi(other);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body: Record<string, unknown> = {
        sku: sku.trim(),
        candidate_prices_paise: validPrices.map((p) => toPaise(p)),
        basis,
        gst_rate_pct: gstRatePct.trim() || null,
        marketplace: marketplace.trim(),
        category: category.trim(),
        fee_type: feeType.trim(),
        as_of_date: asOfDate,
        cogs_paise: cogsUnavailable ? null : cogsRupees.trim() ? toPaise(cogsRupees) : null,
        cogs_unavailable_reason: cogsUnavailable ? cogsUnavailableReason.trim() || null : null,
        shipping_logistics_paise: ship.paise,
        shipping_logistics_unavailable_reason: ship.reason,
        advertising_costs_paise: ads.paise,
        advertising_costs_unavailable_reason: ads.reason,
        return_rto_losses_paise: rtoUnavailable ? null : rtoRupees.trim() ? toPaise(rtoRupees) : null,
        return_rto_losses_unavailable_reason: rtoUnavailable ? rtoUnavailableReason.trim() || null : null,
        other_allocated_costs_paise: oth.paise,
        other_allocated_costs_unavailable_reason: oth.reason,
      };
      const res = await apiFetch<PricingCurveResponse>("/api/v1/cfo/pricing", await getToken(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute the pricing curve"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Pricing Curve">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="SKU"><TextInput value={sku} onChange={setSku} /></Field>
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Category"><TextInput value={category} onChange={setCategory} /></Field>
          <Field label="Fee type"><TextInput value={feeType} onChange={setFeeType} /></Field>
        </div>
        <div>
          <div className="mb-1 t-body-sm" style={{ color: "var(--text-6)" }}>Candidate prices (₹)</div>
          <div className="flex flex-col gap-2">
            {candidatePrices.map((p, idx) => (
              <div key={idx} className="flex gap-2">
                <TextInput value={p} onChange={(v) => updatePrice(idx, v)} placeholder="e.g. 999" />
                <button
                  type="button"
                  onClick={() => removePrice(idx)}
                  className="rounded-lg px-3 py-2 t-body-sm font-semibold"
                  style={{ border: "1px solid var(--border-default)", color: "var(--negative)" }}
                >
                  Remove
                </button>
              </div>
            ))}
            <button type="button" onClick={addPrice} className="w-fit t-meta font-semibold" style={{ color: "var(--text-3)" }}>
              + Add candidate price
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Basis">
            <SelectInput
              value={basis}
              onChange={(v) => setBasis(v as "INCLUSIVE" | "EXCLUSIVE")}
              options={[
                { value: "INCLUSIVE", label: "Inclusive" },
                { value: "EXCLUSIVE", label: "Exclusive" },
              ]}
            />
          </Field>
          <Field label="GST rate % (optional)"><TextInput value={gstRatePct} onChange={setGstRatePct} placeholder="e.g. 18" /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <CostInput label="Shipping/logistics" value={shipping} onChange={setShipping} />
          <CostInput label="Advertising" value={advertising} onChange={setAdvertising} />
          <CostInput label="Other allocated costs" value={other} onChange={setOther} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="mb-1 flex items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
              <input type="checkbox" checked={cogsUnavailable} onChange={(e) => setCogsUnavailable(e.target.checked)} />
              COGS unavailable
            </label>
            {cogsUnavailable ? (
              <TextInput value={cogsUnavailableReason} onChange={setCogsUnavailableReason} placeholder="reason COGS is unavailable" />
            ) : (
              <TextInput value={cogsRupees} onChange={setCogsRupees} placeholder="COGS per unit (₹)" />
            )}
          </div>
          <div>
            <label className="mb-1 flex items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
              <input type="checkbox" checked={rtoUnavailable} onChange={(e) => setRtoUnavailable(e.target.checked)} />
              Return/RTO losses unavailable
            </label>
            {rtoUnavailable ? (
              <TextInput
                value={rtoUnavailableReason}
                onChange={setRtoUnavailableReason}
                placeholder="reason return/RTO losses are unavailable"
              />
            ) : (
              <TextInput value={rtoRupees} onChange={setRtoRupees} placeholder="Return/RTO losses (₹)" />
            )}
          </div>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compute pricing curve" busyLabel="Computing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.curve.map((r) => (
              <CfoMetricResultRow key={r.engineResultRef} label={r.calculationBasis ?? r.metricCode} result={r} />
            ))}
            {result.dataRequestId && <DataRequestNote id={result.dataRequestId} getToken={getToken} />}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 7. Landed cost (POST /cfo/landed-cost) -------------------------------------------

export function LandedCostSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [sku, setSku] = useState("");
  const [targetType, setTargetType] = useState<"SKU" | "ACCOUNT" | "PERIOD">("SKU");
  const [targetRef, setTargetRef] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<LandedCostResponse | null>(null);

  const submit = async () => {
    if (!sku.trim() || !targetRef.trim()) {
      setError("Enter the SKU and the supplier quote's target ref first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<LandedCostResponse>("/api/v1/cfo/landed-cost", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          sku: sku.trim(),
          supplier_quote_target_type: targetType,
          supplier_quote_target_ref: targetRef.trim(),
          quantity: parseInt(quantity, 10) || 1,
          as_of_date: asOfDate || null,
        }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute landed cost"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Landed Cost">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="SKU"><TextInput value={sku} onChange={setSku} /></Field>
          <Field label="Supplier quote target type">
            <SelectInput
              value={targetType}
              onChange={(v) => setTargetType(v as typeof targetType)}
              options={[
                { value: "SKU", label: "SKU" },
                { value: "ACCOUNT", label: "ACCOUNT" },
                { value: "PERIOD", label: "PERIOD" },
              ]}
            />
          </Field>
          <Field label="Supplier quote target ref"><TextInput value={targetRef} onChange={setTargetRef} /></Field>
          <Field label="Quantity"><TextInput type="number" value={quantity} onChange={setQuantity} /></Field>
        </div>
        <Field label="As-of date (optional)"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compute landed cost" busyLabel="Computing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.result ? (
              <CfoMetricResultRow label="Landed cost" result={result.result} />
            ) : (
              <div style={{ color: "var(--text-6)" }}>
                No result.{result.dataRequestId && <DataRequestNote id={result.dataRequestId} getToken={getToken} />}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 8. Supplier ranking (POST /cfo/suppliers/rank) -----------------------------------

export function SupplierRankingSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [sku, setSku] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SupplierRankingResponse | null>(null);

  const submit = async () => {
    if (!sku.trim()) {
      setError("Enter a SKU first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<SupplierRankingResponse>("/api/v1/cfo/suppliers/rank", await getToken(), {
        method: "POST",
        body: JSON.stringify({ sku: sku.trim(), quantity: parseInt(quantity, 10) || 1, as_of_date: asOfDate || null }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not rank suppliers"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Supplier Ranking">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="SKU"><TextInput value={sku} onChange={setSku} /></Field>
          <Field label="Quantity"><TextInput type="number" value={quantity} onChange={setQuantity} /></Field>
          <Field label="As-of date (optional)"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Rank suppliers" busyLabel="Ranking…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-3">
            {result.isSingleQuote && (
              <div style={{ color: "var(--text-6)" }}>Only one active quote — reported as a single quote, not a ranking.</div>
            )}
            {result.ranked.length === 0 ? (
              <div style={{ color: "var(--text-6)" }}>No active supplier quotes found for this SKU.</div>
            ) : (
              <div className="mt-ledger">
                {result.ranked.map((r) => (
                  <div key={r.result.engineResultRef}>
                    <CfoMetricResultRow label={r.supplierName ?? "Supplier"} result={r.result} />
                    <div className="t-meta" style={{ color: "var(--text-6)" }}>
                      lead time: {r.leadTimeDays ?? "—"} days · MOQ: {r.moq ?? "—"} · terms: {r.paymentTerms ?? "—"} ·{" "}
                      {r.reliabilityNote ?? ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {result.quarantined.length > 0 && (
              <div>
                <div className="mb-1 t-body-sm font-semibold" style={{ color: "var(--negative)" }}>Quarantined quotes</div>
                {result.quarantined.map((q) => (
                  <div key={q.adjustmentId} className="t-body-sm" style={{ color: "var(--text-5)" }}>
                    {q.supplierName ?? "Unknown supplier"} — {q.reason}
                  </div>
                ))}
              </div>
            )}
            {result.dataRequestId && <DataRequestNote id={result.dataRequestId} getToken={getToken} />}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 9. Batch size estimate (POST /cfo/batch-size) ------------------------------------

export function BatchSizeSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [sku, setSku] = useState("");
  const [supplierTargetType, setSupplierTargetType] = useState<"SKU" | "ACCOUNT" | "PERIOD">("SKU");
  const [supplierTargetRef, setSupplierTargetRef] = useState("");
  const [budgetTargetType, setBudgetTargetType] = useState<"SKU" | "ACCOUNT">("SKU");
  const [budgetTargetRef, setBudgetTargetRef] = useState("");
  const [lines, setLines] = useState<EditableGstSummaryLine[]>([]);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchSizeResponse | null>(null);

  const updateLine = (idx: number, patch: Partial<EditableGstSummaryLine>) =>
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  const removeLine = (idx: number) => setLines((ls) => ls.filter((_, i) => i !== idx));
  const addLine = () => setLines((ls) => [...ls, newGstSummaryLine()]);
  const generateLineId = (idx: number) => updateLine(idx, { sales_line_id: crypto.randomUUID() });

  const submit = async () => {
    if (!sku.trim() || !supplierTargetRef.trim() || !budgetTargetRef.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in SKU, supplier quote target ref, budget target ref and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const validLines = lines.filter((l) => l.sales_line_id.trim() && l.marketplace.trim() && l.gross_item_amount_rupees.trim());
      const res = await apiFetch<BatchSizeResponse>("/api/v1/cfo/batch-size", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          sku: sku.trim(),
          supplier_quote_target_type: supplierTargetType,
          supplier_quote_target_ref: supplierTargetRef.trim(),
          budget_target_type: budgetTargetType,
          budget_target_ref: budgetTargetRef.trim(),
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
        }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute the batch size estimate"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Batch Size Estimate">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="SKU"><TextInput value={sku} onChange={setSku} /></Field>
          <Field label="Supplier quote target type">
            <SelectInput
              value={supplierTargetType}
              onChange={(v) => setSupplierTargetType(v as typeof supplierTargetType)}
              options={[
                { value: "SKU", label: "SKU" },
                { value: "ACCOUNT", label: "ACCOUNT" },
                { value: "PERIOD", label: "PERIOD" },
              ]}
            />
          </Field>
          <Field label="Supplier quote target ref"><TextInput value={supplierTargetRef} onChange={setSupplierTargetRef} /></Field>
          <Field label="Budget target type">
            <SelectInput
              value={budgetTargetType}
              onChange={(v) => setBudgetTargetType(v as typeof budgetTargetType)}
              options={[
                { value: "SKU", label: "SKU" },
                { value: "ACCOUNT", label: "ACCOUNT" },
              ]}
            />
          </Field>
        </div>
        <Field label="Budget target ref"><TextInput value={budgetTargetRef} onChange={setBudgetTargetRef} /></Field>
        <div>
          <div className="mb-1 t-body-sm" style={{ color: "var(--text-6)" }}>
            Sales history lines (optional — leaving this empty is a valid real case, &quot;never sold&quot;)
          </div>
          <div className="flex flex-col gap-3">
            {lines.map((line, idx) => (
              <div key={idx} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                  <div className="flex gap-2">
                    <TextInput
                      value={line.sales_line_id}
                      onChange={(v) => updateLine(idx, { sales_line_id: v })}
                      placeholder="sales_line_id (UUID)"
                    />
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
                  <TextInput
                    value={line.confidence}
                    onChange={(v) => updateLine(idx, { confidence: v })}
                    placeholder="confidence (default CONFIRMED)"
                  />
                </div>
                <div className="mt-2">
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
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Estimate batch size" busyLabel="Estimating…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.result ? (
              <CfoMetricResultRow label="Batch size estimate" result={result.result} />
            ) : (
              <div style={{ color: "var(--text-6)" }}>
                No estimate.{result.dataRequestId && <DataRequestNote id={result.dataRequestId} getToken={getToken} />}
              </div>
            )}
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              Velocity: {result.velocityStatus}
              {result.velocityUnavailableReason ? ` (${result.velocityUnavailableReason})` : ""} · observed units sold:{" "}
              {result.observedUnitsSold ?? "—"}
            </div>
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              Reference quantity: {result.referenceQuantity ?? "—"} ({result.referenceQuantityBasis ?? "—"}) · lead time:{" "}
              {result.leadTimeDays ?? "—"} days · MOQ: {result.moq ?? "—"}
            </div>
            {result.referenceQuantityCaveatApplies && (
              <div className="t-body-sm" style={{ color: "var(--negative)" }}>{result.referenceQuantityCaveat}</div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 10. Funding readiness (POST /cfo/funding-readiness) ------------------------------

export function FundingReadinessSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [expectedPeriods, setExpectedPeriods] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FundingReadinessResponse | null>(null);

  const submit = async () => {
    if (!periodStart || !periodEnd || !asOfDate) {
      setError("Fill in all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<FundingReadinessResponse>("/api/v1/cfo/funding-readiness", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          period_start: periodStart,
          period_end: periodEnd,
          as_of_date: asOfDate,
          expected_periods: expectedPeriods
            .split(",")
            .map((p) => p.trim())
            .filter(Boolean),
        }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not assemble funding readiness"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Funding Readiness">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <Field label="Expected periods (optional, comma-separated, e.g. 2024-01-01/2024-01-31)">
          <TextInput value={expectedPeriods} onChange={setExpectedPeriods} />
        </Field>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Assemble funding readiness" busyLabel="Assembling…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-3">
            <div>
              <div className="mb-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>Contribution profit history</div>
              {result.contributionProfitHistory.length === 0 ? (
                <div style={{ color: "var(--text-6)" }}>No history available.</div>
              ) : (
                <div className="mt-ledger">
                  {result.contributionProfitHistory.map((r) => (
                    <CfoMetricResultRow key={r.engineResultRef} label={r.asOfDate ?? r.metricCode} result={r} />
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="mb-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>Trend</div>
              {result.trend.length === 0 ? (
                <div style={{ color: "var(--text-6)" }}>No trend available.</div>
              ) : (
                <div className="mt-ledger">
                  {result.trend.map((r) => (
                    <CfoMetricResultRow key={r.engineResultRef} label={r.calculationBasis ?? r.metricCode} result={r} />
                  ))}
                </div>
              )}
            </div>
            {result.gaps.length > 0 && (
              <div>
                <div className="mb-1 t-body-sm font-semibold" style={{ color: "var(--negative)" }}>Gaps</div>
                {result.gaps.map((g, i) => (
                  <div key={i} className="t-body-sm" style={{ color: "var(--text-5)" }}>
                    {g.kind}
                    {g.period ? ` (${g.period})` : ""}: {g.reason}
                  </div>
                ))}
              </div>
            )}
            <div>
              <div className="mb-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
                Deferred sections (never a score/rating — AC19)
              </div>
              {result.deferredSections.map((s, i) => (
                <div key={i} className="t-body-sm" style={{ color: "var(--text-6)" }}>{s.name}: {s.reason}</div>
              ))}
            </div>
            {result.dataRequestId && <DataRequestNote id={result.dataRequestId} getToken={getToken} />}
          </div>
        )}
      </div>
    </Section>
  );
}
