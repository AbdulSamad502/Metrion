"use client";

import { createContext, useContext, useId, useRef } from "react";
import { Spinner } from "@/components/ui/LoadingState";
import { useToast } from "@/components/ui/Toast";
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

/** The marketplaces Metrion supports (the business profile only allows these three). The value is the exact upper-case id the backend already receives. */
export const MARKETPLACE_OPTIONS = [
  { value: "AMAZON", label: "Amazon" },
  { value: "FLIPKART", label: "Flipkart" },
  { value: "MEESHO", label: "Meesho" },
];

/** A marketplace chooser for the forms where it is required: same three ids the free-text box used to take, nothing else, and nothing chosen until the seller picks one. */
export function MarketplaceSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <SelectInput value={value} onChange={onChange} options={[{ value: "", label: "Choose a marketplace" }, ...MARKETPLACE_OPTIONS]} />;
}

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** The start and end dates a shortcut fills in. Calendar dates only (the seller's own local day), written as the same YYYY-MM-DD the date fields hold; no money and no new parameter. */
export function presetPeriods(now: Date = new Date()): { id: string; label: string; start: string; end: string }[] {
  const y = now.getFullYear();
  const m = now.getMonth();
  const thirtyAgo = new Date(y, m, now.getDate() - 29);
  return [
    { id: "this-month", label: "This month", start: iso(new Date(y, m, 1)), end: iso(now) },
    { id: "last-month", label: "Last month", start: iso(new Date(y, m - 1, 1)), end: iso(new Date(y, m, 0)) },
    { id: "last-30", label: "Last 30 days", start: iso(thirtyAgo), end: iso(now) },
  ];
}

/** Shortcuts that fill the existing period start and end fields. They send nothing and change no other field; the seller can still type any dates. */
export function PeriodPresets({ onPick }: { onPick: (start: string, end: string) => void }) {
  return (
    <div className="col-span-full flex flex-wrap items-center gap-2" role="group" aria-label="Fill in the period">
      <span className="t-meta" style={{ color: "var(--text-5)" }}>Quick pick</span>
      {presetPeriods().map((p) => (
        <button key={p.id} type="button" onClick={() => onPick(p.start, p.end)} className="mt-chip mt-focus min-h-10 rounded-full px-3.5 t-body-sm font-medium" style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}>
          {p.label}
        </button>
      ))}
    </div>
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

/** Copies a result's full reference (ID). The result row only shows its first characters, and the "Compare two results" form needs the whole ID. The message appears only
 * after the browser has accepted the copy; if it refuses, it says so instead. */
function CopyIdButton({ id }: { id: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      toast.success("ID copied.");
    } catch {
      toast.error("Could not copy the ID. Your browser did not allow it.");
    }
  };
  return (
    <button type="button" onClick={copy} className="mt-btn mt-focus ml-2 min-h-10 rounded-lg px-2.5 t-meta font-semibold" style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}>
      Copy ID
    </button>
  );
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
        <CopyIdButton id={result.engineResultRef} />
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
