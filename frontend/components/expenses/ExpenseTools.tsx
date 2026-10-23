"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import { ErrorText, Field, SelectInput, SubmitButton, TextInput } from "@/components/cfo/primitives";
import { friendlyApiError } from "@/lib/apiErrors";
import { money, post, type ExpenseRecord, type Getter, type LedgerMeta } from "@/lib/expenseLedger";
import { percentToBps } from "@/lib/pnlText";
import {
  KIND_LABEL, REFUND_REASON_LABEL, SKIP_REASON_LABEL, STATUS_LABEL, buildTemplateBody, buildTemplateRefundBody, createTemplate, downloadCsv, endTemplate, importFile, loadTemplates, materialise, refundTemplate,
  type ExpenseTemplate, type ImportStatus, type ImportSummary, type MaterialiseResponse, type TemplateForm, type TemplateKind,
} from "@/lib/expenseTools";

const STATUS_TONE: Record<ImportStatus, Tone> = { OK: "accent", ERROR: "negative", DUPLICATE: "neutral", PROBABLE_MATCH: "warning" };

/** The first of next month as a date text, for the "make entries up to" box. Dates only, no money. */
function defaultThroughMonth(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`;
}

const EMPTY_FORM: TemplateForm = { kind: "MONTHLY", category: "", vendor: "", amount: "", rate: "", months: "", effectiveFrom: "" };

/** Recurring, spread-over-months and per-order templates. A template is a standing instruction, not an entry: "Create the entries" makes ordinary entries that wait in the
 * review queue (nothing recurring is counted until you confirm it), one per month, and never twice. Amounts per month and the spread come from the backend's engine. */
export function RecurringPanel({ getToken, meta, onChanged }: { getToken: Getter; meta: LedgerMeta; onChanged: () => Promise<void> }) {
  const [templates, setTemplates] = useState<ExpenseTemplate[] | null>(null);
  const [form, setForm] = useState<TemplateForm>(EMPTY_FORM);
  const [through, setThrough] = useState(defaultThroughMonth);
  const [result, setResult] = useState<MaterialiseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refunding, setRefunding] = useState<ExpenseTemplate | null>(null);
  const [refundDate, setRefundDate] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [refundNote, setRefundNote] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setTemplates((await loadTemplates(getToken)).templates);
    } catch (e) {
      setError(friendlyApiError(e, "Could not load the recurring entries"));
    }
  }, [getToken]);
  useEffect(() => {
    (async () => {
      await reload();
    })();
  }, [reload]);

  const set = <K extends keyof TemplateForm>(key: K, value: TemplateForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const save = async () => {
    const built = buildTemplateBody(form);
    if (!built.ok) return setError(built.error);
    setBusy(true);
    setError(null);
    try {
      await createTemplate(getToken, built.body);
      setForm(EMPTY_FORM);
      await reload();
    } catch (e) {
      setError(friendlyApiError(e, "Could not save the recurring entry"));
    } finally {
      setBusy(false);
    }
  };

  const make = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await materialise(getToken, through));
      await onChanged();
    } catch (e) {
      setError(friendlyApiError(e, "Could not create the entries"));
    } finally {
      setBusy(false);
    }
  };

  const sendRefund = async () => {
    if (!refunding) return;
    const built = buildTemplateRefundBody(refundDate, refundAmount);
    if (!built.ok) return setError(built.error);
    setBusy(true);
    setError(null);
    try {
      const out = await refundTemplate(getToken, refunding.templateKey, built.body);
      setRefundNote(`Done. From ${out.remainingFrom}, ${money(out.remainingPaise)} is left to spread over ${out.remainingMonths} months. Earlier months are not changed.`);
      setRefunding(null);
      setRefundAmount("");
      await reload();
    } catch (e) {
      const code = (e as { detail?: { code?: string } }).detail?.code;
      setError(code && REFUND_REASON_LABEL[code] ? REFUND_REASON_LABEL[code] : friendlyApiError(e, "Could not record the refund"));
    } finally {
      setBusy(false);
    }
  };

  const end = async (t: ExpenseTemplate) => {
    setBusy(true);
    setError(null);
    try {
      await endTemplate(getToken, t.templateKey, t.effectiveFrom > defaultThroughMonth() ? t.effectiveFrom : defaultThroughMonth());
      await reload();
    } catch (e) {
      setError(friendlyApiError(e, "Could not end the recurring entry"));
    } finally {
      setBusy(false);
    }
  };

  const amountField = form.kind === "MONTHLY" || form.kind === "AMORTIZED";
  return (
    <div className="flex flex-col gap-6">
      <Section title="Your recurring entries" hint="Rent, software, a yearly fee spread over months, or a cost per order. They create entries that wait for your confirmation.">
        {templates === null ? null : templates.length === 0 ? (
          <EmptyState compact title="Nothing recurring yet" description="Add one below." />
        ) : (
          <div className="mt-ledger">
            {templates.map((t) => (
              <div key={t.templateKey} className="mt-ledger__row" data-testid="template-row">
                <div>
                  <div className="t-body" style={{ color: "var(--text-3)" }}>{t.vendor ?? t.categoryLabel} · {KIND_LABEL[t.kind]}</div>
                  <div className="t-micro" style={{ color: "var(--text-6)" }}>
                    From {t.effectiveFrom}{t.effectiveTo ? ` to ${t.effectiveTo}` : ""}{t.kind === "AMORTIZED" && t.amortizationMonths ? ` · over ${t.amortizationMonths} months` : ""}{t.ended ? " · ended" : ""}
                  </div>
                  {(t.kind === "PER_ORDER" || t.kind === "PER_UNIT") && (
                    <div className="t-micro" style={{ color: "var(--text-6)" }}>Priced from your sales for each finished month: the rate times the {t.kind === "PER_ORDER" ? "order" : "unit"} count.</div>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="t-metric">{money(String(t.kind === "PER_ORDER" || t.kind === "PER_UNIT" ? t.ratePaise : t.amountPaise))}</span>
                  {t.kind === "AMORTIZED" && !t.ended && <button type="button" disabled={busy} className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => { setRefunding(t); setRefundNote(null); }}>Refund</button>}
                  {!t.ended && <button type="button" disabled={busy} className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => end(t)}>End</button>}
                </div>
              </div>
            ))}
          </div>
        )}
        {refunding && (
          <div className="mt-4 grid grid-cols-1 items-end gap-3 rounded-xl p-3 sm:grid-cols-4" style={{ border: "1px solid var(--border-default)" }} data-testid="refund-panel">
            <p className="t-body-sm sm:col-span-4" style={{ color: "var(--text-4)" }}>Refund of {refunding.vendor ?? refunding.categoryLabel}: reduces what is left to spread from the refund month on. Months already made are not changed.</p>
            <Field label="Refund date"><TextInput type="date" value={refundDate} onChange={setRefundDate} /></Field>
            <Field label="Refund amount (₹)"><TextInput value={refundAmount} onChange={setRefundAmount} /></Field>
            <SubmitButton onClick={sendRefund} busy={busy} label="Record the refund" busyLabel="Saving…" />
            <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-2 t-body-sm" onClick={() => setRefunding(null)}>Cancel</button>
          </div>
        )}
        {refundNote && <p className="mt-3 t-body-sm" style={{ color: "var(--text-4)" }} data-testid="refund-note">{refundNote}</p>}
        <div className="mt-4 grid grid-cols-1 items-end gap-3 sm:grid-cols-3">
          <Field label="Create the entries up to"><TextInput type="date" value={through} onChange={setThrough} /></Field>
          <SubmitButton onClick={make} busy={busy} label="Create the entries" busyLabel="Creating…" />
        </div>
        {result && (
          <div className="mt-3 t-body-sm" style={{ color: "var(--text-4)" }} data-testid="materialise-result">
            {result.created.length} new {result.created.length === 1 ? "entry" : "entries"} are waiting for review; {result.alreadyMaterialised} already existed.
            {result.skipped.map((s, i) => <div key={`${s.templateKey}-${i}`} style={{ color: "var(--warning)" }}>{SKIP_REASON_LABEL[s.reason] ?? s.reason}</div>)}
          </div>
        )}
      </Section>

      <Section title="Add a recurring entry" hint="Amounts are in rupees. A cost per order or per unit is the rate times that finished month's order or unit count from your uploaded sales; if the count is not available it creates nothing and says why.">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Kind">
            <SelectInput value={form.kind} onChange={(v) => set("kind", v as TemplateKind)} options={(Object.keys(KIND_LABEL) as TemplateKind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
          </Field>
          <Field label="Category">
            <SelectInput value={form.category} onChange={(v) => set("category", v)} options={[{ value: "", label: "Choose…" }, ...meta.categories.map((c) => ({ value: c.id, label: c.label }))]} />
          </Field>
          <Field label="Vendor (optional)"><TextInput value={form.vendor} onChange={(v) => set("vendor", v)} /></Field>
          <Field label="Starts"><TextInput type="date" value={form.effectiveFrom} onChange={(v) => set("effectiveFrom", v)} /></Field>
          {amountField ? (
            <Field label={form.kind === "AMORTIZED" ? "Total amount (₹)" : "Amount each month (₹)"}><TextInput value={form.amount} onChange={(v) => set("amount", v)} placeholder="e.g. 1200 or 1200.50" /></Field>
          ) : (
            <Field label={form.kind === "PER_ORDER" ? "Rate per order (₹)" : "Rate per unit (₹)"}><TextInput value={form.rate} onChange={(v) => set("rate", v)} placeholder="e.g. 5" /></Field>
          )}
          {form.kind === "AMORTIZED" && <Field label="Spread over (months)"><TextInput value={form.months} onChange={(v) => set("months", v)} placeholder="e.g. 12" /></Field>}
        </div>
        <div className="mt-4"><SubmitButton onClick={save} busy={busy} label="Save recurring entry" busyLabel="Saving…" /></div>
      </Section>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

/** CSV import and the accountant export. Import: download the fixed template, choose a file, check it (nothing is saved), then import. Imported rows wait in the review queue;
 * a source id already in the ledger is skipped and listed, and a row that looks like an existing entry is kept and flagged, never dropped. The file is not stored. */
export function ImportExportPanel({ getToken, onChanged }: { getToken: Getter; onChanged: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [committed, setCommitted] = useState(false);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const run = async (commit: boolean) => {
    if (!file) return setError("Choose a CSV file first.");
    setBusy(true);
    setError(null);
    try {
      const out = await importFile(getToken, file, commit, skipInvalid);
      setSummary(out);
      setCommitted(commit);
      if (commit) await onChanged();
    } catch (e) {
      setError(friendlyApiError(e, commit ? "Could not import the file" : "Could not check the file"));
    } finally {
      setBusy(false);
    }
  };

  const download = async (path: string, name: string) => {
    setError(null);
    try {
      await downloadCsv(getToken, path, name);
    } catch (e) {
      setError(friendlyApiError(e, "Could not download the file"));
    }
  };

  const problems = summary ? summary.counts.ERROR : 0;
  return (
    <div className="flex flex-col gap-6">
      <Section title="Import expenses from a CSV file" hint="Use the fixed template. Amounts are in rupees (1200 or 1200.50). Nothing is saved until you choose Import, and imported rows wait for your confirmation.">
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-2 t-body-sm" onClick={() => download("/import/template", "expense-import-template.csv")}>Download the template</button>
          <input
            ref={input} type="file" accept=".csv,text/csv" aria-label="CSV file" className="t-body-sm"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setSummary(null); setCommitted(false); }}
          />
          <SubmitButton onClick={() => run(false)} busy={busy} label="Check the file" busyLabel="Checking…" />
        </div>
        {summary && summary.fileErrors.length > 0 && (
          <ul role="alert" className="mt-3 list-disc pl-5 t-body-sm" style={{ color: "var(--negative)" }}>{summary.fileErrors.map((m) => <li key={m}>{m}</li>)}</ul>
        )}
        {summary && summary.fileErrors.length === 0 && (
          <div className="mt-4 flex flex-col gap-3" data-testid="import-summary">
            <p className="t-body-sm" style={{ color: "var(--text-4)" }}>
              {committed ? "Imported. " : "Checked, nothing saved yet. "}
              {summary.counts.OK} ready, {summary.counts.PROBABLE_MATCH} look like existing entries, {summary.counts.DUPLICATE} already in the ledger, {summary.counts.ERROR} with a problem.
              {committed && ` ${summary.created?.length ?? 0} waiting for review; ${summary.alreadyImported ?? 0} had been imported before.`}
            </p>
            <div className="mt-table-wrap">
              <table className="mt-table">
                <thead><tr><th>Row</th><th>Result</th><th>Date</th><th>Vendor</th><th className="text-right">Amount</th><th>Note</th></tr></thead>
                <tbody>
                  {summary.rows.map((r) => (
                    <tr key={r.row} data-testid="import-row">
                      <td>{r.row}</td>
                      <td><StatusBadge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</StatusBadge></td>
                      <td>{r.date ?? "—"}</td>
                      <td>{r.vendor ?? "—"}</td>
                      <td className="text-right">{r.amountPaise === null ? "—" : money(String(r.amountPaise))}</td>
                      <td>{[...r.errors, r.note].filter(Boolean).join(" ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!committed && (
              <div className="flex flex-wrap items-center gap-3">
                {problems > 0 && (
                  <label className="flex items-center gap-2 t-body-sm" style={{ color: "var(--text-4)" }}>
                    <input type="checkbox" checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} className="mt-focus h-5 w-5" style={{ accentColor: "var(--accent)" }} />
                    Import the good rows and leave the {problems} with a problem
                  </label>
                )}
                <button
                  type="button" onClick={() => run(true)} disabled={busy || (problems > 0 && !skipInvalid)}
                  className="mt-btn mt-focus rounded-lg px-4 py-2 t-body-sm font-bold disabled:opacity-50" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
                >
                  {busy ? "Importing…" : "Import"}
                </button>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title="Export for your accountant" hint="Every entry in every state, including voided ones, with its status. Made when you ask and not stored by Metrion.">
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-2 t-body-sm" onClick={() => download("/export", "expense-ledger.csv")}>Download the ledger (CSV)</button>
          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-2 t-body-sm" onClick={() => download("/export?history=true", "expense-ledger-history.csv")}>Download with full history</button>
        </div>
      </Section>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

type ShareRow = { sku: string; percent: string };
type Basis = "EQUAL" | "EXPLICIT_SHARES" | "NET_REVENUE" | "UNITS" | "ORDERS";
const BASIS_OPTIONS: { value: Basis; label: string }[] = [
  { value: "EQUAL", label: "Equally" },
  { value: "EXPLICIT_SHARES", label: "By the percentage I enter" },
  { value: "NET_REVENUE", label: "By each SKU's revenue this period" },
  { value: "UNITS", label: "By each SKU's units kept this period" },
  { value: "ORDERS", label: "By each SKU's orders this period" },
];

/** Splits one advertising or storage entry across several SKUs. The seller chooses the split (equally, or as a percentage of the entry per SKU); the backend's engine does the
 * arithmetic when totals are built, the part not assigned stays visible as an unassigned business-level amount, and the entry's total never changes. Shares are sent as whole
 * basis points typed as percentages (30 -> 3000); the page adds nothing up. */
export function AssignPanel({ getToken, record, onCancel, onDone }: { getToken: Getter; record: ExpenseRecord; onCancel: () => void; onDone: () => Promise<void> }) {
  const [basis, setBasis] = useState<Basis>("EQUAL");
  const [rows, setRows] = useState<ShareRow[]>([{ sku: "", percent: "" }, { sku: "", percent: "" }]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const setRow = (i: number, patch: Partial<ShareRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const save = async () => {
    const shares: { sku: string; bp?: number }[] = [];
    for (const [i, r] of rows.entries()) {
      if (!r.sku.trim()) return setError(`Enter the SKU on row ${i + 1}, or remove the row.`);
      if (basis !== "EXPLICIT_SHARES") {
        shares.push({ sku: r.sku.trim() }); // equal, or the SKU's own figures decide: no percentage is sent
        continue;
      }
      const bps = percentToBps(r.percent);
      if (!bps.ok) return setError(`Row ${i + 1}: ${bps.reason}`);
      if (!/^[1-9][0-9]{0,3}$/.test(bps.value)) return setError(`Row ${i + 1}: enter a share above 0% and up to 100%.`);
      shares.push({ sku: r.sku.trim(), bp: JSON.parse(bps.value) as number });
    }
    setBusy(true);
    setError(null);
    try {
      await post(getToken, `/${record.id}/assign`, { basis, shares });
      await onDone();
    } catch (e) {
      setError(friendlyApiError(e, "Could not save the split"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title={`Split across SKUs: ${record.vendor ?? record.categoryLabel}`} hint="You choose the split. Whatever cannot be assigned (for example a SKU with no sales data this period) stays visible as unassigned, never as zero, and the entry's total does not change.">
      <div className="flex flex-col gap-3" data-testid="assign-panel">
        <Field label="Split">
          <SelectInput value={basis} onChange={(v) => setBasis(BASIS_OPTIONS.find((o) => o.value === v)?.value ?? "EQUAL")} options={BASIS_OPTIONS} />
        </Field>
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label={`SKU ${i + 1}`}><TextInput value={r.sku} onChange={(v) => setRow(i, { sku: v })} /></Field>
            {basis === "EXPLICIT_SHARES" && <Field label={`Share of SKU ${i + 1} (%)`}><TextInput value={r.percent} onChange={(v) => setRow(i, { percent: v })} /></Field>}
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-1 t-micro" onClick={() => setRows((rs) => [...rs, { sku: "", percent: "" }])}>Add a SKU</button>
          {rows.length > 1 && <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-1 t-micro" onClick={() => setRows((rs) => rs.slice(0, -1))}>Remove the last</button>}
          <SubmitButton onClick={save} busy={busy} label="Save the split" busyLabel="Saving…" />
          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-1 t-micro" onClick={onCancel}>Cancel</button>
        </div>
        <ErrorText>{error}</ErrorText>
      </div>
    </Section>
  );
}
