"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { Section } from "@/components/ui/Section";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { isOpenRequest } from "@/lib/useNotifications";
import { useHashTab } from "@/lib/useHashTab";
import {
  ApiError,
  apiFetch,
  type AnalyzeGstLinesResponse,
  type AnomalyCheckResponse,
  type BatchSizeResponse,
  type BudgetStatus,
  type CfoPreviewResponse,
  type DataRequestItem,
  type UploadOutcome,
  type ExpenseListResponse,
  type FundingReadinessResponse,
  type GstLookupResponse,
  type GstLookupResult,
  type GstPeriodSummaryResponse,
  type LandedCostResponse,
  type ManualAdjustmentIdResponse,
  type MetricResult,
  type PeriodComparisonResponse,
  type PeriodPnlMetricResult,
  type PeriodPnlResponse,
  type PricingCurveResponse,
  type ReconcileResponse,
  type SupplierRankingResponse,
} from "@/lib/api";

const CFO_TABS = [
  { id: "overview", label: "Overview" },
  { id: "profitability", label: "Profitability" },
  { id: "cash", label: "Cash & reconciliation" },
  { id: "gst", label: "GST" },
  { id: "anomalies", label: "Anomalies & requests" },
  { id: "import", label: "Import data" },
] as const;

const CFO_TAB_BLURBS: Record<(typeof CFO_TABS)[number]["id"], string> = {
  overview: "Financial health, the strategic briefing, a Leak Shield preview and the goal everything is measured against.",
  profitability: "True contribution profit, period comparison, price/margin curves, landed cost, suppliers and batch sizing.",
  cash: "Reconcile settlements to invoices, track expenses against a budget, and check funding readiness.",
  gst: "Line-level GST analysis, period summaries and HSN/rate lookup. Informational — not tax advice.",
  anomalies: "Statistical anomaly checks, and the inputs the CFO is asking you for.",
  import: "Upload marketplace reports. Metrion reads files you upload — it never connects to a marketplace account.",
};

/** The CFO workspace. Each tab groups the existing, real direct-execution tools
 * (`backend/src/backend/api/v1/cfo.py`) by the question they answer — nothing here computes or
 * invents a figure: every section calls a real route and renders exactly what comes back,
 * including genuine UNAVAILABLE / error / empty states. Money is entered/rendered in rupees and
 * converted to/from paise at the edge only. */
export default function CfoPage() {
  return (
    <DashboardShell title="CFO" subtitle="Profit, cash, GST and leaks — computed deterministically from your uploaded data">
      <CfoWorkspace />
    </DashboardShell>
  );
}

function CfoWorkspace() {
  const { getToken } = useAuth();
  const [tab, setTab] = useHashTab(CFO_TABS.map((t) => t.id), "overview");

  // The latest upload and a bump counter, so Import history refreshes and can surface a duplicate.
  const [lastUpload, setLastUpload] = useState<UploadOutcome | null>(null);
  const [importsTick, setImportsTick] = useState(0);

  const [dataRequests, setDataRequests] = useState<DataRequestItem[] | null>(null);
  const [dataRequestsError, setDataRequestsError] = useState<string | null>(null);

  const reloadDataRequests = async () => {
    try {
      const token = await getToken();
      const rows = await apiFetch<DataRequestItem[]>("/api/v1/cfo/data-requests", token);
      setDataRequests(rows);
    } catch (e) {
      setDataRequestsError(e instanceof ApiError ? e.message : "Could not reach the backend");
    }
  };

  useEffect(() => {
    (async () => {
      await reloadDataRequests();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openRequests = (dataRequests ?? []).filter(isOpenRequest).length;
  const tabs = CFO_TABS.map((t) => ({ ...t, count: t.id === "anomalies" ? openRequests : null }));

  return (
    <div className="mt-content flex flex-col gap-7">
      <div className="flex flex-col gap-3">
        <Tabs tabs={tabs} active={tab} onChange={setTab} label="CFO workspace" idPrefix="cfo" />
        <p className="t-body" style={{ color: "var(--text-5)" }}>
          {CFO_TAB_BLURBS[tab as (typeof CFO_TABS)[number]["id"]]}
        </p>
      </div>

      <TabPanel id="overview" active={tab} idPrefix="cfo">
        <div className="grid grid-cols-1 items-start gap-x-10 gap-y-9 xl:grid-cols-2">
          <FinancialHealthSection getToken={getToken} />
          <StrategicBriefingSection getToken={getToken} />
          <CfoPreviewSection getToken={getToken} />
          <SellerGoalSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="profitability" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <PeriodPnlSection getToken={getToken} />
          <PeriodComparisonSection getToken={getToken} />
          <PricingCurveSection getToken={getToken} />
          <LandedCostSection getToken={getToken} />
          <SupplierRankingSection getToken={getToken} />
          <BatchSizeSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="cash" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <ReconcileSection getToken={getToken} />
          <ExpenseTrackerSection getToken={getToken} />
          <FundingReadinessSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="gst" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <GstLineAnalysisSection getToken={getToken} />
          <GstPeriodSummarySection getToken={getToken} />
          <GstLookupSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="anomalies" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <DataRequestsSection rows={dataRequests} error={dataRequestsError} onReload={reloadDataRequests} />
          <AnomalyCheckSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="import" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <IngestUploadSection
            getToken={getToken}
            onUploaded={(outcome) => {
              setLastUpload(outcome);
              setImportsTick((n) => n + 1);
            }}
          />
          <ImportHistory getToken={getToken} refreshTick={importsTick} lastUpload={lastUpload} />
        </div>
      </TabPanel>
    </div>
  );
}

// --- Shared primitives (same inline CSS-variable convention ceo-hub/page.tsx uses) ----

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-5)" }}>{label}</label>
      {children}
    </div>
  );
}

function TextInput({
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
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
    />
  );
}

function SelectInput({
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

function SubmitButton({
  onClick,
  busy,
  label,
  busyLabel,
  primary = false,
}: {
  onClick: () => void;
  busy: boolean;
  label: string;
  busyLabel: string;
  /** The one green action of a view; every other submit is a neutral secondary button. */
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`mt-btn mt-focus w-fit rounded-lg px-4 py-2 t-body font-bold disabled:cursor-not-allowed ${primary ? "" : "mt-btn-secondary"}`}
      style={primary ? { background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 } : { opacity: busy ? 0.6 : 1 }}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div className="t-body-sm" style={{ color: "var(--negative)" }}>
      {children}
    </div>
  );
}

function rupees(paise: number | null): string {
  return paise === null ? "—" : `₹${(paise / 100).toFixed(2)}`;
}

function toPaise(rupeesStr: string): number {
  return Math.round(parseFloat(rupeesStr) * 100);
}

/** Mirrors ceo-hub/page.tsx's own `MetricResultRow` — reused for every `MetricResult`-shaped
 * object across this whole page. Renders `valueFraction` (percentage metrics, e.g.
 * `CONTRIBUTION_MARGIN_PCT`) INSTEAD OF `valuePaise` when present, matching the backend's own
 * "populated instead of, never alongside" contract. */
function CfoMetricResultRow({ label, result }: { label: string; result: MetricResult | PeriodPnlMetricResult }) {
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

type EditableComponentRow = { component_kind: string; component_code: string; source_side: string; amount_rupees: string };

function newComponentRow(): EditableComponentRow {
  return { component_kind: "", component_code: "", source_side: "", amount_rupees: "" };
}

function componentRowsToPayload(rows: EditableComponentRow[]) {
  return rows
    .filter((r) => r.component_kind.trim() && r.component_code.trim() && r.source_side.trim() && r.amount_rupees.trim())
    .map((r) => ({
      component_kind: r.component_kind.trim(),
      component_code: r.component_code.trim(),
      source_side: r.source_side.trim(),
      amount_paise: toPaise(r.amount_rupees),
    }));
}

function ComponentRowsEditor({
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

type EditableGstSummaryLine = {
  sales_line_id: string;
  marketplace: string;
  document_type: string;
  quantity: string;
  gross_item_amount_rupees: string;
  components: EditableComponentRow[];
  confidence: string;
};

function newGstSummaryLine(): EditableGstSummaryLine {
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

// --- 1. Expense tracker (PUT/GET /cfo/expenses, PUT /cfo/expenses/budget, GET /cfo/expenses/budget-status) --

// The only five real §7.2.1 expense-pool categories the backend's `_EXPENSE_CATEGORIES`
// registry accepts (backend/src/backend/services/cfo_actions.py) — a free-text category
// here would 400/500 on every submit, since `enter_expense`/`set_expense_budget`/
// `check_expense_budget` all reject anything outside this exact, lowercase set.
const EXPENSE_CATEGORIES = ["advertising", "packaging", "storage", "logistics", "other"] as const;

function ExpenseTrackerSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [addCategory, setAddCategory] = useState<string>(EXPENSE_CATEGORIES[0]);
  const [addAmount, setAddAmount] = useState("");
  const [addMarketplace, setAddMarketplace] = useState("");
  // Free-text description (e.g. "petrol for delivery run", "travel to supplier meeting") —
  // stored as manual_adjustment.reason, the field enter_expense already accepted but this form
  // never collected, leaving "other" entries with no way to say what they actually were.
  const [addDescription, setAddDescription] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [addResult, setAddResult] = useState<ManualAdjustmentIdResponse | null>(null);

  const addExpense = async () => {
    if (!addCategory.trim() || !addAmount.trim()) {
      setAddError("Enter a category and amount first.");
      return;
    }
    setAddBusy(true);
    setAddError(null);
    setAddResult(null);
    try {
      const value: Record<string, unknown> = { amount_paise: toPaise(addAmount) };
      if (addMarketplace.trim()) value.marketplace = addMarketplace.trim();
      const res = await apiFetch<ManualAdjustmentIdResponse>("/api/v1/cfo/expenses", await getToken(), {
        method: "PUT",
        body: JSON.stringify({
          target_type: "ACCOUNT",
          target_ref: "default",
          field: `expense.${addCategory.trim()}`,
          value,
          reason: addDescription.trim() || null,
        }),
      });
      setAddResult(res);
      setAddCategory("");
      setAddAmount("");
      setAddMarketplace("");
      setAddDescription("");
    } catch (e) {
      setAddError(e instanceof ApiError ? e.message : "Could not add expense");
    } finally {
      setAddBusy(false);
    }
  };

  const [listPeriodStart, setListPeriodStart] = useState("");
  const [listPeriodEnd, setListPeriodEnd] = useState("");
  const [listCategory, setListCategory] = useState("");
  // "" means "no category filter" for List/Budget/Status below — GET /cfo/expenses only
  // rejects a category when one is actually supplied, so an empty filter must stay empty,
  // never default to a real category value.
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [listResult, setListResult] = useState<ExpenseListResponse | null>(null);

  const loadExpenses = async () => {
    setListBusy(true);
    setListError(null);
    try {
      const params = new URLSearchParams();
      if (listPeriodStart) params.set("period_start", listPeriodStart);
      if (listPeriodEnd) params.set("period_end", listPeriodEnd);
      if (listCategory.trim()) params.set("category", listCategory.trim());
      const qs = params.toString();
      const res = await apiFetch<ExpenseListResponse>(`/api/v1/cfo/expenses${qs ? `?${qs}` : ""}`, await getToken());
      setListResult(res);
    } catch (e) {
      setListError(e instanceof ApiError ? e.message : "Could not load expenses");
      setListResult(null);
    } finally {
      setListBusy(false);
    }
  };

  const [budgetCategory, setBudgetCategory] = useState<string>(EXPENSE_CATEGORIES[0]);
  const [budgetAmount, setBudgetAmount] = useState("");
  const [budgetPeriodStart, setBudgetPeriodStart] = useState("");
  const [budgetPeriodEnd, setBudgetPeriodEnd] = useState("");
  const [budgetBusy, setBudgetBusy] = useState(false);
  const [budgetError, setBudgetError] = useState<string | null>(null);
  const [budgetResult, setBudgetResult] = useState<ManualAdjustmentIdResponse | null>(null);

  const setBudget = async () => {
    if (!budgetCategory.trim() || !budgetAmount.trim() || !budgetPeriodStart || !budgetPeriodEnd) {
      setBudgetError("Fill in category, amount and both period dates first.");
      return;
    }
    setBudgetBusy(true);
    setBudgetError(null);
    setBudgetResult(null);
    try {
      const res = await apiFetch<ManualAdjustmentIdResponse>("/api/v1/cfo/expenses/budget", await getToken(), {
        method: "PUT",
        body: JSON.stringify({
          category: budgetCategory.trim(),
          amount_paise: toPaise(budgetAmount),
          period_start: budgetPeriodStart,
          period_end: budgetPeriodEnd,
        }),
      });
      setBudgetResult(res);
    } catch (e) {
      setBudgetError(e instanceof ApiError ? e.message : "Could not set budget");
    } finally {
      setBudgetBusy(false);
    }
  };

  const [statusCategory, setStatusCategory] = useState<string>(EXPENSE_CATEGORIES[0]);
  const [statusPeriodStart, setStatusPeriodStart] = useState("");
  const [statusPeriodEnd, setStatusPeriodEnd] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusResult, setStatusResult] = useState<BudgetStatus | null>(null);

  const checkStatus = async () => {
    if (!statusCategory.trim() || !statusPeriodStart || !statusPeriodEnd) {
      setStatusError("Fill in category and both period dates first.");
      return;
    }
    setStatusBusy(true);
    setStatusError(null);
    try {
      const params = new URLSearchParams({
        category: statusCategory.trim(),
        period_start: statusPeriodStart,
        period_end: statusPeriodEnd,
      });
      const res = await apiFetch<BudgetStatus>(`/api/v1/cfo/expenses/budget-status?${params.toString()}`, await getToken());
      setStatusResult(res);
    } catch (e) {
      setStatusError(e instanceof ApiError ? e.message : "Could not check budget status");
      setStatusResult(null);
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <Section title="Expense Tracker">
      <div className="flex flex-col gap-6">
        <div>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>Add expense</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label="Category">
              <SelectInput
                value={addCategory}
                onChange={setAddCategory}
                options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
            </Field>
            <Field label="Amount (₹)">
              <TextInput value={addAmount} onChange={setAddAmount} placeholder="e.g. 499" />
            </Field>
            <Field label="Marketplace (optional)">
              <TextInput value={addMarketplace} onChange={setAddMarketplace} placeholder="AMAZON" />
            </Field>
          </div>
          <div className="mt-3">
            <Field label="Description (optional) — e.g. travel, petrol, courier">
              <TextInput value={addDescription} onChange={setAddDescription} placeholder="What was this expense for?" />
            </Field>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={addExpense} busy={addBusy} label="Add expense" busyLabel="Adding…" />
          </div>
          <ErrorText>{addError}</ErrorText>
          {addResult && (
            <div className="mt-1 t-body-sm" style={{ color: "var(--accent)" }}>
              Added — manual adjustment <code>{addResult.manualAdjustmentId.slice(0, 8)}</code>
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>List expenses</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label="Period start (optional)">
              <TextInput type="date" value={listPeriodStart} onChange={setListPeriodStart} />
            </Field>
            <Field label="Period end (optional)">
              <TextInput type="date" value={listPeriodEnd} onChange={setListPeriodEnd} />
            </Field>
            <Field label="Category (optional)">
              <SelectInput
                value={listCategory}
                onChange={setListCategory}
                options={[{ value: "", label: "— All categories —" }, ...EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))]}
              />
            </Field>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={loadExpenses} busy={listBusy} label="List expenses" busyLabel="Loading…" />
          </div>
          <ErrorText>{listError}</ErrorText>
          {listResult && (
            <div className="mt-3">
              {listResult.entries.length === 0 ? (
                <div style={{ color: "var(--text-6)" }}>No expenses recorded yet for this filter.</div>
              ) : (
                <div className="mt-table-wrap"><table className="mt-table">
                  <thead>
                    <tr style={{ color: "var(--text-6)" }}>
                      <th className="pb-2 font-semibold">Category</th>
                      <th className="pb-2 font-semibold">Description</th>
                      <th className="pb-2 font-semibold">Amount</th>
                      <th className="pb-2 font-semibold">Target</th>
                      <th className="pb-2 font-semibold">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {listResult.entries.map((e) => (
                      <tr key={e.manualAdjustmentId} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                        <td className="py-2" style={{ color: "var(--text-3)" }}>{e.category}</td>
                        <td className="py-2" style={{ color: "var(--text-5)" }}>{e.reason ?? "—"}</td>
                        <td className="py-2" style={{ color: "var(--text-3)" }}>{rupees(e.amountPaise)}</td>
                        <td className="py-2" style={{ color: "var(--text-5)" }}>{e.targetType}/{e.targetRef}</td>
                        <td className="py-2" style={{ color: "var(--text-5)" }}>{new Date(e.createdAt).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              <div className="mt-2 t-body" style={{ color: "var(--text-2)" }}>Total: {rupees(listResult.totalPaise)}</div>
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>Set category budget</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <Field label="Category">
              <SelectInput
                value={budgetCategory}
                onChange={setBudgetCategory}
                options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
            </Field>
            <Field label="Budget ceiling (₹)"><TextInput value={budgetAmount} onChange={setBudgetAmount} placeholder="e.g. 20000" /></Field>
            <Field label="Period start"><TextInput type="date" value={budgetPeriodStart} onChange={setBudgetPeriodStart} /></Field>
            <Field label="Period end"><TextInput type="date" value={budgetPeriodEnd} onChange={setBudgetPeriodEnd} /></Field>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={setBudget} busy={budgetBusy} label="Set budget" busyLabel="Saving…" />
          </div>
          <ErrorText>{budgetError}</ErrorText>
          {budgetResult && (
            <div className="mt-1 t-body-sm" style={{ color: "var(--accent)" }}>
              Saved — manual adjustment <code>{budgetResult.manualAdjustmentId.slice(0, 8)}</code>
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>Check budget status</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label="Category">
              <SelectInput
                value={statusCategory}
                onChange={setStatusCategory}
                options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
            </Field>
            <Field label="Period start"><TextInput type="date" value={statusPeriodStart} onChange={setStatusPeriodStart} /></Field>
            <Field label="Period end"><TextInput type="date" value={statusPeriodEnd} onChange={setStatusPeriodEnd} /></Field>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={checkStatus} busy={statusBusy} label="Check status" busyLabel="Checking…" />
          </div>
          <ErrorText>{statusError}</ErrorText>
          {statusResult && (
            <div className="mt-2 t-body" style={{ color: "var(--text-2)" }}>
              {statusResult.noBudgetSet ? (
                <div style={{ color: "var(--text-6)" }}>No budget set for this category/period.</div>
              ) : (
                <>
                  <div>
                    Spent: {rupees(statusResult.spentPaise)} · Budget: {rupees(statusResult.budgetPaise)} · Remaining:{" "}
                    {rupees(statusResult.remainingPaise)}
                  </div>
                  <div style={{ color: statusResult.exceeded ? "var(--negative)" : "var(--accent)" }}>
                    {statusResult.exceeded ? "Budget exceeded" : "Within budget"}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

// --- 2. Period P&L (POST /cfo/pnl) --------------------------------------------------

function PeriodPnlSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not compute period P&L");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Period P&L (quick single-line)">
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
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} placeholder="AMAZON" /></Field>
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

// --- 3. GST line analysis (POST /cfo/gst/analyze-lines) -----------------------------

type EditableGstLine = { line_ref: string; listed_rupees: string; basis: "INCLUSIVE" | "EXCLUSIVE"; rate_pct: string };

function newGstLine(): EditableGstLine {
  return { line_ref: "", listed_rupees: "", basis: "INCLUSIVE", rate_pct: "" };
}

function GstLineAnalysisSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        lines: validLines.map((l) => ({
          line_ref: l.line_ref.trim(),
          listed_paise: toPaise(l.listed_rupees),
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
      setError(e instanceof ApiError ? e.message : "Could not analyze GST lines");
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

function GstPeriodSummarySection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not compute the GST period summary");
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

function GstLookupSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not run the GST applicability lookup");
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
      setAcceptError(e instanceof ApiError ? e.message : "Could not accept this GST rate");
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

// --- 6. Pricing curve (POST /cfo/pricing) --------------------------------------------

function PricingCurveSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
  const [shipping, setShipping] = useState("0");
  const [advertising, setAdvertising] = useState("0");
  const [other, setOther] = useState("0");
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
        shipping_logistics_paise: toPaise(shipping || "0"),
        advertising_costs_paise: toPaise(advertising || "0"),
        return_rto_losses_paise: rtoUnavailable ? null : rtoRupees.trim() ? toPaise(rtoRupees) : null,
        return_rto_losses_unavailable_reason: rtoUnavailable ? rtoUnavailableReason.trim() || null : null,
        other_allocated_costs_paise: toPaise(other || "0"),
      };
      const res = await apiFetch<PricingCurveResponse>("/api/v1/cfo/pricing", await getToken(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not compute the pricing curve");
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
          <Field label="Shipping/logistics (₹)"><TextInput value={shipping} onChange={setShipping} /></Field>
          <Field label="Advertising (₹)"><TextInput value={advertising} onChange={setAdvertising} /></Field>
          <Field label="Other allocated costs (₹)"><TextInput value={other} onChange={setOther} /></Field>
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
            {result.dataRequestId && (
              <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
                Data request raised: <code>{result.dataRequestId.slice(0, 8)}</code>
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 7. Landed cost (POST /cfo/landed-cost) -------------------------------------------

function LandedCostSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not compute landed cost");
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
                No result — data request raised{result.dataRequestId ? `: ${result.dataRequestId.slice(0, 8)}` : ""}.
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 8. Supplier ranking (POST /cfo/suppliers/rank) -----------------------------------

function SupplierRankingSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not rank suppliers");
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
            {result.dataRequestId && (
              <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
                Data request raised: <code>{result.dataRequestId.slice(0, 8)}</code>
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 9. Batch size estimate (POST /cfo/batch-size) ------------------------------------

function BatchSizeSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not compute the batch size estimate");
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
                No estimate — data request raised{result.dataRequestId ? `: ${result.dataRequestId.slice(0, 8)}` : ""}.
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

function FundingReadinessSection({ getToken }: { getToken: () => Promise<string | null> }) {
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
      setError(e instanceof ApiError ? e.message : "Could not assemble funding readiness");
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
            {result.dataRequestId && (
              <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
                Data request raised: <code>{result.dataRequestId.slice(0, 8)}</code>
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 11. Leak Shield / Reconciliation (POST /cfo/reconcile) ---------------------------

function ReconcileSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [marketplace, setMarketplace] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReconcileResponse | null>(null);

  const submit = async () => {
    if (!marketplace.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in marketplace and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<ReconcileResponse>("/api/v1/cfo/reconcile", await getToken(), {
        method: "POST",
        body: JSON.stringify({ marketplace: marketplace.trim(), period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not run Leak Shield reconciliation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Leak Shield / Reconciliation">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} placeholder="AMAZON / FLIPKART / MEESHO" /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Run reconciliation" busyLabel="Reconciling…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              run <code>{result.reconciliationRunId.slice(0, 8)}</code> · matches: {result.matchCount} · exceptions:{" "}
              {result.exceptionCount} · ambiguous: {result.ambiguousMatchCount} · missing dates: {result.datesMissingCount}
            </div>
            {result.findings.length === 0 ? (
              <div style={{ color: "var(--text-6)" }}>No leak findings for this period.</div>
            ) : (
              <div className="mt-table-wrap"><table className="mt-table">
                <thead>
                  <tr style={{ color: "var(--text-6)" }}>
                    <th className="pb-2 font-semibold">Category</th>
                    <th className="pb-2 font-semibold">Severity</th>
                    <th className="pb-2 font-semibold">Amount</th>
                    <th className="pb-2 font-semibold">Marketplace</th>
                    <th className="pb-2 font-semibold">Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {result.findings.map((f) => (
                    <tr key={f.leakFindingId} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{f.leakCategory}</td>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{f.severity}</td>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{rupees(f.amountPaise)}</td>
                      <td className="py-2" style={{ color: "var(--text-5)" }}>{f.marketplace}</td>
                      <td className="py-2" style={{ color: "var(--text-5)" }}><code>{f.engineResultRef.slice(0, 8)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 12. CFO Preview / free-tier gate (POST /cfo/preview) -----------------------------

function CfoPreviewSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [marketplace, setMarketplace] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CfoPreviewResponse | null>(null);

  const submit = async () => {
    if (!marketplace.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in marketplace and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<CfoPreviewResponse>("/api/v1/cfo/preview", await getToken(), {
        method: "POST",
        body: JSON.stringify({ marketplace: marketplace.trim(), period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the CFO preview");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="CFO Preview (free-tier)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Load preview" busyLabel="Loading…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2 t-body" style={{ color: "var(--text-2)" }}>
            <div>
              Headline total: {rupees(result.headlineTotalPaise)}
              {result.headlineEngineResultRef && (
                <span style={{ color: "var(--text-6)" }}> (ref: <code>{result.headlineEngineResultRef.slice(0, 8)}</code>)</span>
              )}
            </div>
            <div>
              Affected SKUs:{" "}
              {result.affectedSkuCountUnavailable
                ? `UNAVAILABLE — ${result.affectedSkuCountUnavailable}`
                : result.affectedSkuCount ?? "—"}
            </div>
            {result.revealedFinding ? (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                {result.revealedFinding.leakCategory} · {result.revealedFinding.severity} ·{" "}
                {rupees(result.revealedFinding.amountPaise)} · SKU: {result.revealedFinding.sku ?? "—"}
              </div>
            ) : (
              <div style={{ color: "var(--text-6)" }}>No finding revealed.</div>
            )}
            <div style={{ color: "var(--text-6)" }}>{result.lockedFindingsCount} more finding(s) locked — upgrade to see them all.</div>
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 13. Anomaly check (POST /cfo/anomaly-check) ---------------------------------------

function AnomalyCheckSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [targetRef, setTargetRef] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [includeNarration, setIncludeNarration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnomalyCheckResponse | null>(null);

  const submit = async () => {
    if (!targetRef.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in target ref and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<AnomalyCheckResponse>("/api/v1/cfo/anomaly-check", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          target_ref: targetRef.trim(),
          period_start: periodStart,
          period_end: periodEnd,
          as_of_date: asOfDate,
          include_narration: includeNarration,
        }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not run the anomaly check");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Anomaly Check">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Target ref (SKU/ACCOUNT/MARKETPLACE)"><TextInput value={targetRef} onChange={setTargetRef} /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <label className="flex items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
          <input type="checkbox" checked={includeNarration} onChange={(e) => setIncludeNarration(e.target.checked)} />
          Include narration (calls the local LLM — slower)
        </label>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Run anomaly check" busyLabel="Checking…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              metric: {result.metric} · series length: {result.seriesLength}
            </div>
            {result.methods.map((m) => (
              <div
                key={m.method}
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <div style={{ color: "var(--text-2)" }}><strong>{m.method}</strong></div>
                {m.flag && (
                  <div style={{ color: m.flag.fired ? "var(--negative)" : "var(--text-3)" }}>
                    {m.flag.fired ? `Fired — severity ${m.flag.severity}, score ${m.flag.score}` : `Not fired — score ${m.flag.score}`}
                  </div>
                )}
                {m.insufficientHistory && (
                  <div style={{ color: "var(--text-6)" }}>Insufficient history — {m.insufficientHistory.reason}</div>
                )}
                {m.zeroVariance && <div style={{ color: "var(--text-6)" }}>Zero variance — {m.zeroVariance.reason}</div>}
                {m.configurationGap && <div style={{ color: "var(--text-6)" }}>Configuration gap — {m.configurationGap.reason}</div>}
              </div>
            ))}
            {result.narration && (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
              >
                {result.narration}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 14. Period comparison / Brain-3 narration (POST /cfo/period-comparison) ----------

function PeriodComparisonSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [resultAId, setResultAId] = useState("");
  const [resultBId, setResultBId] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PeriodComparisonResponse | null>(null);

  const submit = async () => {
    if (!resultAId.trim() || !resultBId.trim() || !asOfDate) {
      setError("Fill in both engine result refs and an as-of date first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<PeriodComparisonResponse>("/api/v1/cfo/period-comparison", await getToken(), {
        method: "POST",
        body: JSON.stringify({ result_a_id: resultAId.trim(), result_b_id: resultBId.trim(), as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not compare these two periods");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Period Comparison (Brain-3 narration)">
      <div className="flex flex-col gap-3">
        <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
          Both ids must be real, already-persisted <code>engineResultRef</code> values for the same metric code — e.g.
          two different periods&apos; Contribution Profit refs copied from the Period P&amp;L section above.
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Result A id (engineResultRef)"><TextInput value={resultAId} onChange={setResultAId} placeholder="UUID" /></Field>
          <Field label="Result B id (engineResultRef)"><TextInput value={resultBId} onChange={setResultBId} placeholder="UUID" /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compare periods" busyLabel="Comparing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.delta ? (
              <CfoMetricResultRow label="Delta" result={result.delta} />
            ) : (
              <div style={{ color: "var(--text-6)" }}>
                No delta — data request raised{result.dataRequestId ? `: ${result.dataRequestId.slice(0, 8)}` : ""}.
              </div>
            )}
            {result.narration && (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
              >
                {result.narration}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 15. Data requests (GET /cfo/data-requests) ----------------------------------------

function DataRequestsSection({
  rows,
  error,
  onReload,
}: {
  rows: DataRequestItem[] | null;
  error: string | null;
  onReload: () => void;
}) {
  return (
    <Section title="Data Requests">
      <div className="flex flex-col gap-3">
        <button type="button" onClick={onReload} className="w-fit t-meta font-semibold" style={{ color: "var(--text-3)" }}>
          Refresh
        </button>
        {error && <div className="t-body-sm" style={{ color: "var(--negative)" }}>{error}</div>}
        {rows === null ? (
          <div style={{ color: "var(--text-6)" }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: "var(--text-6)" }}>No data requests raised yet.</div>
        ) : (
          <div className="mt-table-wrap"><table className="mt-table">
            <thead>
              <tr style={{ color: "var(--text-6)" }}>
                <th className="pb-2 font-semibold">Requested field</th>
                <th className="pb-2 font-semibold">Reason</th>
                <th className="pb-2 font-semibold">Blocking metric</th>
                <th className="pb-2 font-semibold">Status</th>
                <th className="pb-2 font-semibold">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <td className="py-2" style={{ color: "var(--text-3)" }}>{r.requestedField}</td>
                  <td className="py-2" style={{ color: "var(--text-3)" }}>{r.reason ?? "—"}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{r.blockingMetric ?? "—"}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{r.status}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{new Date(r.createdAt).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </Section>
  );
}

// --- Ingestion, seller goal, financial health, strategic briefing (cfo-agent.md §6.16/§7.5) --

function IngestUploadSection({
  getToken,
  onUploaded,
}: {
  getToken: () => Promise<string | null>;
  onUploaded: (outcome: UploadOutcome) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [marketplace, setMarketplace] = useState("MEESHO");
  const [adapterId, setAdapterId] = useState("meesho.orders.v1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const submit = async () => {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const token = await getToken();
      const form = new FormData();
      form.append("file", file);
      const qs = new URLSearchParams({ marketplace, adapter_id: adapterId }).toString();
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1/cfo/ingest?${qs}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: form,
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail ? JSON.stringify(json.detail) : "Upload failed");
      setResult(json);
      if (typeof json.reportFileId === "string") {
        onUploaded({ reportFileId: json.reportFileId, duplicate: Boolean(json.duplicate), filename: file.name });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not upload the file");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Upload marketplace report (CSV)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Adapter id (e.g. meesho.orders.v1)"><TextInput value={adapterId} onChange={setAdapterId} /></Field>
          <Field label="File">
            <input type="file" accept=".csv" className="t-body-sm w-full min-w-0 max-w-full" style={{ color: "var(--text-4)" }} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Upload & ingest" busyLabel="Ingesting…" primary /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="t-body-sm" role="status" style={{ color: "var(--text-3)" }}>
            {result.duplicate
              ? "This exact file was already imported — nothing was ingested again. See it in Import history below."
              : `Ingested. ${String(result.rowCountAccepted ?? "?")} of ${String(result.rowCountRead ?? "?")} rows accepted, ${String(result.rowCountRejected ?? 0)} rejected, ${String(result.rowCountDuplicate ?? 0)} duplicates skipped. Open it in Import history below to inspect what was saved.`}
          </div>
        )}
      </div>
    </Section>
  );
}

function SellerGoalSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [targetMarginPct, setTargetMarginPct] = useState("");
  const [priorityCategory, setPriorityCategory] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await apiFetch<ManualAdjustmentIdResponse>("/api/v1/cfo/seller-goal", await getToken(), {
        method: "PUT",
        body: JSON.stringify({
          target_margin_pct: targetMarginPct.trim() || null,
          priority_category: priorityCategory.trim() || null,
          note: note.trim() || null,
        }),
      });
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the goal");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Seller goal (context for Strategic Briefing narration only)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Target margin % (optional)"><TextInput value={targetMarginPct} onChange={setTargetMarginPct} placeholder="15.00" /></Field>
          <Field label="Priority category (optional)"><TextInput value={priorityCategory} onChange={setPriorityCategory} placeholder="reduce_fees" /></Field>
          <Field label="Note (optional)"><TextInput value={note} onChange={setNote} /></Field>
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Save goal" busyLabel="Saving…" /></div>
        <ErrorText>{error}</ErrorText>
        {saved && <div className="t-body-sm" style={{ color: "var(--accent)" }}>Saved.</div>}
      </div>
    </Section>
  );
}

function FinancialHealthSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const submit = async () => {
    if (!periodStart || !periodEnd || !asOfDate) {
      setError("Fill in all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<Record<string, unknown>>("/api/v1/cfo/financial-health", await getToken(), {
        method: "POST",
        body: JSON.stringify({ period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not compute financial health");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Financial Health Band">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Compute" busyLabel="Computing…" /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="t-body" style={{ color: "var(--text-3)" }}>
            Overall band: <strong>{String(result.overallBand ?? "UNAVAILABLE")}</strong>
            {result.unavailableReason ? <span style={{ color: "var(--text-6)" }}> — {String(result.unavailableReason)}</span> : null}
            <pre className="mt-2 t-meta" style={{ color: "var(--text-5)" }}>{JSON.stringify(result.perMetricBands, null, 2)}</pre>
          </div>
        )}
      </div>
    </Section>
  );
}

function StrategicBriefingSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [includeNarration, setIncludeNarration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ signals: Record<string, unknown>[]; narrative: string | null } | null>(null);

  const submit = async () => {
    if (!periodStart || !periodEnd || !asOfDate) {
      setError("Fill in all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<{ signals: Record<string, unknown>[]; narrative: string | null }>(
        "/api/v1/cfo/strategic-briefing",
        await getToken(),
        {
          method: "POST",
          body: JSON.stringify({
            period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate, include_narration: includeNarration,
          }),
        },
      );
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not build the briefing");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Strategic Briefing (deterministic signals + one narration call)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <label className="flex items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
          <input type="checkbox" checked={includeNarration} onChange={(e) => setIncludeNarration(e.target.checked)} />
          Include narration (calls the local LLM — slower)
        </label>
        <div><SubmitButton onClick={submit} busy={busy} label="Build briefing" busyLabel="Building…" /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            {result.signals.length === 0 ? (
              <div style={{ color: "var(--text-6)" }}>No signals for this period.</div>
            ) : (
              result.signals.map((s, i) => (
                <div key={i} className="t-body-sm" style={{ color: "var(--text-3)" }}>
                  [{String(s.severityLabel)}] {String(s.headline)} — {String(s.recommendedActionType)}
                </div>
              ))
            )}
            {result.narrative && <div className="mt-2 t-body" style={{ color: "var(--text-3)" }}>{result.narrative}</div>}
          </div>
        )}
      </div>
    </Section>
  );
}
