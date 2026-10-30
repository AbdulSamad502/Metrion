"use client";

import { useState } from "react";
import { Section } from "@/components/ui/Section";
import { apiFetch, type PeriodPnlResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { CfoMetricResultRow, ComponentRowsEditor, EditableComponentRow, ErrorText, Field, SelectInput, SubmitButton, TextInput, componentRowsToPayload, rupees, toPaise, PeriodPresets, MarketplaceSelect } from "@/components/cfo/primitives";

// --- 2. Period P&L (POST /cfo/pnl) --------------------------------------------------

export function PeriodPnlSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [salesLineId, setSalesLineId] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [documentType, setDocumentType] = useState("INVOICE");
  const [quantity, setQuantity] = useState("1");
  const [grossAmount, setGrossAmount] = useState("");
  const [components, setComponents] = useState<EditableComponentRow[]>([]);
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [recognitionState, setRecognitionState] = useState<"RECOGNISED" | "REALIZED" | "UNAVAILABLE">("RECOGNISED");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PeriodPnlResponse | null>(null);

  const generateId = () => setSalesLineId(crypto.randomUUID());

  const submit = async () => {
    if (
      !salesLineId.trim() ||
      !marketplace.trim() ||
      !documentType.trim() ||
      !grossAmount.trim() ||
      !periodStart ||
      !periodEnd ||
      !asOfDate
    ) {
      setError("Fill in sales line id, marketplace, document type, gross amount and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        lines: [
          {
            sales_line_id: salesLineId.trim(),
            marketplace: marketplace.trim(),
            document_type: documentType.trim(),
            quantity: parseInt(quantity, 10) || 0,
            gross_item_amount_paise: toPaise(grossAmount),
            components: componentRowsToPayload(components),
          },
        ],
        period_start: periodStart,
        period_end: periodEnd,
        as_of_date: asOfDate,
        recognition_state: recognitionState,
      };
      const res = await apiFetch<PeriodPnlResponse>("/api/v1/cfo/pnl", await getToken(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute period P&L"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Period profit & loss (one line)" hint="Net realized revenue, contribution profit, margin, fee ratio and return rate for the sales line you enter, worked out by the engine.">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Sales line id (UUID)">
            <div className="flex gap-2">
              <TextInput value={salesLineId} onChange={setSalesLineId} placeholder="UUID" />
              <button
                type="button"
                onClick={generateId}
                className="rounded-lg px-3 py-2 t-meta font-semibold"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}
              >
                Generate
              </button>
            </div>
          </Field>
          <Field label="Marketplace"><MarketplaceSelect value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Document type"><TextInput value={documentType} onChange={setDocumentType} placeholder="INVOICE" /></Field>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Quantity"><TextInput type="number" value={quantity} onChange={setQuantity} /></Field>
          <Field label="Gross item amount (₹)"><TextInput value={grossAmount} onChange={setGrossAmount} placeholder="e.g. 999" /></Field>
          <Field label="Recognition state">
            <SelectInput
              value={recognitionState}
              onChange={(v) => setRecognitionState(v as typeof recognitionState)}
              options={[
                { value: "RECOGNISED", label: "RECOGNISED" },
                { value: "REALIZED", label: "REALIZED" },
                { value: "UNAVAILABLE", label: "UNAVAILABLE" },
              ]}
            />
          </Field>
        </div>
        <div>
          <div className="mb-1 t-body-sm" style={{ color: "var(--text-6)" }}>Line components</div>
          <ComponentRowsEditor rows={components} onChange={setComponents} />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
          <PeriodPresets onPick={(s, e) => { setPeriodStart(s); setPeriodEnd(e); }} />
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compute period P&L" busyLabel="Computing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            <CfoMetricResultRow label="Net Realized Revenue" result={result.nrr} />
            <CfoMetricResultRow label="Contribution Profit" result={result.contributionProfit} />
            <CfoMetricResultRow label="Contribution Margin %" result={result.marginPct} />
            <CfoMetricResultRow label="Fee Ratio %" result={result.feeRatioPct} />
            <CfoMetricResultRow label="Return Rate %" result={result.returnRatePct} />
            <div className="t-body-sm" data-testid="pnl-advertising" style={{ color: "var(--text-6)" }}>
              {result.advertisingEntered ? `Advertising: ${rupees(result.advertisingCostsPaise)}` : "Advertising: Not entered in this calculation"}
            </div>
            {result.marketplaceFeeFlags.length > 0 && (
              <div className="t-body-sm" style={{ color: "var(--negative)" }}>
                Duplicate-fee-candidate warnings: {result.marketplaceFeeFlags.join(", ")}
              </div>
            )}
            {result.dataRequestId && (
              <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
                Data request raised: <code>{result.dataRequestId.slice(0, 8)}</code> (COGS or RTO classification unavailable)
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}
