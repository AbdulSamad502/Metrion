"use client";

import { createContext, useContext, useId, useRef } from "react";
import { Spinner } from "@/components/ui/LoadingState";
import { rupeesToPaise } from "@/lib/costInput";
import { type MetricResult, type PeriodPnlMetricResult } from "@/lib/api";

// --- Shared primitives (same inline CSS-variable convention ceo-hub/page.tsx uses) ----

export const FieldIdContext = createContext<string | undefined>(undefined);

/** The label is tied to its control (clicking it focuses the control, and assistive technology reads it as the control's name). */
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-5)" }}>{label}</label>
      <FieldIdContext.Provider value={id}>{children}</FieldIdContext.Provider>
    </div>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  const fieldId = useContext(FieldIdContext);
  return (
    <input
      id={fieldId}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
    />
  );
}

export function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      id={useContext(FieldIdContext)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function SubmitButton({
  onClick,
  busy,
  label,
  busyLabel,
  primary = false,
}: {
  onClick: () => void | Promise<void>;
  busy: boolean;
  label: string;
  busyLabel: string;
  /** The one green action of a view; every other submit is a neutral secondary button. */
  primary?: boolean;
}) {
  // `busy` only disables the button after the parent re-renders, so a fast double-click could send two requests. This ref drops the second click at once.
  const inFlight = useRef(false);
  const press = () => {
    if (busy || inFlight.current) return;
    inFlight.current = true;
    const done = () => {
      inFlight.current = false;
    };
    const out = onClick();
    if (out instanceof Promise) void out.finally(done);
    else done();
  };
  return (
    <button
      type="button"
      onClick={press}
      disabled={busy}
      aria-busy={busy}
      className={`mt-btn mt-focus inline-flex w-fit items-center gap-2 rounded-lg px-4 py-2 t-body font-bold disabled:cursor-not-allowed ${primary ? "" : "mt-btn-secondary"}`}
      style={primary ? { background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 } : { opacity: busy ? 0.6 : 1 }}
    >
      {busy && <Spinner size={12} />}
      {busy ? busyLabel : label}
    </button>
  );
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>
      {children}
    </div>
  );
}

export function rupees(paise: number | null): string {
  return paise === null ? "—" : `₹${(paise / 100).toFixed(2)}`;
}

export function toPaise(rupeesStr: string): number {
  return rupeesToPaise(rupeesStr) ?? Number.NaN; // exact integer parsing, never a float; an unparsable amount stays NaN (rejected by the server) rather than a guess
}

/** Mirrors ceo-hub/page.tsx's own `MetricResultRow` — reused for every `MetricResult`-shaped
 * object across this whole page. Renders `valueFraction` (percentage metrics, e.g.
 * `CONTRIBUTION_MARGIN_PCT`) INSTEAD OF `valuePaise` when present, matching the backend's own
 * "populated instead of, never alongside" contract. */
export function CfoMetricResultRow({ label, result }: { label: string; result: MetricResult | PeriodPnlMetricResult }) {
  const fraction = "valueFraction" in result ? result.valueFraction : null;
  const paise = result.valuePaise;
  // Colour carries meaning only where the sign does: a loss is always negative; a positive figure
  // is "positive" (green) only for profit-type metrics — revenue or cost being > 0 is not good news.
  const isProfit = /PROFIT|MARGIN|DELTA/i.test(result.metricCode ?? "");
  const moneyColor = paise === null ? "var(--text-1)" : paise < 0 ? "var(--negative)" : paise > 0 && isProfit ? "var(--positive)" : "var(--text-1)";
  return (
    <div className="mt-ledger__row">
      <div className="t-body" style={{ color: "var(--text-3)" }}>
        {label}
      </div>
      <div className="text-right t-metric" style={{ color: "var(--text-1)" }}>
        {!result.isAvailable ? (
          <span className="t-body font-semibold" style={{ color: "var(--text-5)" }}>
            Unavailable
          </span>
        ) : fraction !== null ? (
          <span>{fraction}%</span>
        ) : paise !== null ? (
          <span style={{ color: moneyColor }}>
            {paise >= 0 ? "+" : "-"}₹{(Math.abs(paise) / 100).toFixed(2)}
          </span>
        ) : (
          <span style={{ color: "var(--text-5)" }}>—</span>
        )}
      </div>
      <div className="mt-ledger__meta">
        {!result.isAvailable && result.unavailableReason ? <span style={{ color: "var(--warning)" }}>{result.unavailableReason} · </span> : null}
        confidence {result.confidence} · basis {result.calculationBasis ?? "—"} · ref <code>{result.engineResultRef.slice(0, 8)}</code>
      </div>
    </div>
  );
}

// --- CanonicalLine component-row builder, shared by P&L / GST period summary / batch size --

export type EditableComponentRow = { component_kind: string; component_code: string; source_side: string; amount_rupees: string };

export function newComponentRow(): EditableComponentRow {
  return { component_kind: "", component_code: "", source_side: "", amount_rupees: "" };
}

export function componentRowsToPayload(rows: EditableComponentRow[]) {
  return rows
    .filter((r) => r.component_kind.trim() && r.component_code.trim() && r.source_side.trim() && r.amount_rupees.trim())
    .map((r) => ({
      component_kind: r.component_kind.trim(),
      component_code: r.component_code.trim(),
      source_side: r.source_side.trim(),
      amount_paise: toPaise(r.amount_rupees),
    }));
}

export function ComponentRowsEditor({
  rows,
  onChange,
}: {
  rows: EditableComponentRow[];
  onChange: (rows: EditableComponentRow[]) => void;
}) {
  const update = (idx: number, patch: Partial<EditableComponentRow>) =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const remove = (idx: number) => onChange(rows.filter((_, i) => i !== idx));
  const add = () => onChange([...rows, newComponentRow()]);
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row, idx) => (
        <div key={idx} className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          <TextInput value={row.component_kind} onChange={(v) => update(idx, { component_kind: v })} placeholder="component_kind" />
          <TextInput value={row.component_code} onChange={(v) => update(idx, { component_code: v })} placeholder="component_code" />
          <TextInput value={row.source_side} onChange={(v) => update(idx, { source_side: v })} placeholder="source_side" />
          <TextInput value={row.amount_rupees} onChange={(v) => update(idx, { amount_rupees: v })} placeholder="amount ₹" />
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
        + Add component row
      </button>
    </div>
  );
}

export type EditableGstSummaryLine = {
  sales_line_id: string;
  marketplace: string;
  document_type: string;
  quantity: string;
  gross_item_amount_rupees: string;
  components: EditableComponentRow[];
  confidence: string;
};

export function newGstSummaryLine(): EditableGstSummaryLine {
  return {
    sales_line_id: "",
    marketplace: "",
    document_type: "INVOICE",
    quantity: "1",
    gross_item_amount_rupees: "",
    components: [],
    confidence: "CONFIRMED",
  };
}

/** A file picker named by its Field label (the label's `htmlFor` reaches it through the shared field id). */
export function FileInput({ accept, className, style, onChange }: { accept?: string; className?: string; style?: React.CSSProperties; onChange: React.ChangeEventHandler<HTMLInputElement> }) {
  const id = useContext(FieldIdContext);
  return <input id={id} type="file" accept={accept} className={className} style={style} onChange={onChange} />;
}
