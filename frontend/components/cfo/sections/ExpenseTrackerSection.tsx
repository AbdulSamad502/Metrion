"use client";

import { useState } from "react";
import { Section } from "@/components/ui/Section";
import { Spinner } from "@/components/ui/LoadingState";
import { useToast } from "@/components/ui/Toast";
import { apiFetch, type BudgetStatus, type ExpenseListResponse, type ManualAdjustmentIdResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { ErrorText, Field, SelectInput, SubmitButton, TextInput, rupees, toPaise } from "@/components/cfo/primitives";
import { Pill } from "@/components/overview/parts";

// --- 1. Expense tracker (PUT/GET /cfo/expenses, PUT /cfo/expenses/budget, GET /cfo/expenses/budget-status) --

// The only five real §7.2.1 expense-pool categories the backend's `_EXPENSE_CATEGORIES`
// registry accepts (backend/src/backend/services/cfo_actions.py) — a free-text category
// here would 400/500 on every submit, since `enter_expense`/`set_expense_budget`/
// `check_expense_budget` all reject anything outside this exact, lowercase set.
const EXPENSE_CATEGORIES = ["advertising", "packaging", "storage", "logistics", "other"] as const;

export function ExpenseTrackerSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const toast = useToast();
  const [addCategory, setAddCategory] = useState<string>(EXPENSE_CATEGORIES[0]);
  const [addAmount, setAddAmount] = useState("");
  const [addMarketplace, setAddMarketplace] = useState("");
  // Free-text description (e.g. "petrol for delivery run", "travel to supplier meeting") —
  // stored as manual_adjustment.reason, the field enter_expense already accepted but this form
  // never collected, leaving "other" entries with no way to say what they actually were.
  const [addDescription, setAddDescription] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const addExpense = async () => {
    if (!addCategory.trim() || !addAmount.trim()) {
      setAddError("Enter a category and amount first.");
      return;
    }
    setAddBusy(true);
    setAddError(null);
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
      toast.success(`Expense added (ref ${res.manualAdjustmentId.slice(0, 8)}).`);
      setAddCategory(EXPENSE_CATEGORIES[0]); // not "": an empty category would make the next add fail
      if (listResult) void loadExpenses(listQuery); // the list on screen no longer includes this entry, so refresh it with the same filters
      setAddAmount("");
      setAddMarketplace("");
      setAddDescription("");
    } catch (e) {
      setAddError(friendlyApiError(e, "Could not add expense"));
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
  // The filters and time the list ON SCREEN was loaded with, so it never reads as newer or broader than it is (the inputs above may have changed since).
  const [listQuery, setListQuery] = useState("");
  const [listLoadedAt, setListLoadedAt] = useState<string | null>(null);

  const loadExpenses = async (queryOverride?: string) => {
    setListBusy(true);
    setListError(null);
    try {
      const params = new URLSearchParams();
      if (queryOverride === undefined) {
        if (listPeriodStart) params.set("period_start", listPeriodStart);
        if (listPeriodEnd) params.set("period_end", listPeriodEnd);
        if (listCategory.trim()) params.set("category", listCategory.trim());
      }
      const qs = queryOverride ?? params.toString();
      const res = await apiFetch<ExpenseListResponse>(`/api/v1/cfo/expenses${qs ? `?${qs}` : ""}`, await getToken());
      setListResult(res);
      setListQuery(qs);
      setListLoadedAt(new Date().toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }));
    } catch (e) {
      // A failed refresh keeps the last list that did load; the notice below says so.
      setListError(friendlyApiError(e, "Could not load expenses"));
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

  const setBudget = async () => {
    if (!budgetCategory.trim() || !budgetAmount.trim() || !budgetPeriodStart || !budgetPeriodEnd) {
      setBudgetError("Fill in category, amount and both period dates first.");
      return;
    }
    setBudgetBusy(true);
    setBudgetError(null);
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
      toast.success(`Budget saved (ref ${res.manualAdjustmentId.slice(0, 8)}).`);
    } catch (e) {
      setBudgetError(friendlyApiError(e, "Could not set budget"));
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
  const [statusShown, setStatusShown] = useState(""); // which category and period the result on screen answers

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
      setStatusShown(`${statusCategory.trim()}, ${statusPeriodStart} to ${statusPeriodEnd}`);
    } catch (e) {
      setStatusError(friendlyApiError(e, "Could not check budget status")); // the earlier result, if any, stays and is labelled with its own category and period
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <Section title="Expense tracker">
      <div className="exp-grid">
        <div className="exp-panel exp-add">
          <h3 className="exp-title">Add expense</h3>
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
              <TextInput value={addMarketplace} onChange={setAddMarketplace} placeholder="e.g. Amazon" />
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
        </div>

        <div className="exp-panel exp-list">
          <h3 className="exp-title">List expenses</h3>
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
            <SubmitButton onClick={() => loadExpenses()} busy={listBusy} label="List expenses" busyLabel="Loading…" />
          </div>
          <ErrorText>{listError}</ErrorText>
          {listResult && (
            <div className="mt-3" aria-busy={listBusy}>
              <div className="mb-2 flex flex-wrap items-center gap-2 t-meta" style={{ color: "var(--text-5)" }}>
                <span>
                  {listQuery ? `Filtered: ${listQuery.replace(/&/g, ", ").replace(/=/g, " ")}` : "All expenses"} · loaded {listLoadedAt}
                  {listError ? " · could not refresh, this is the last list that loaded" : ""}
                </span>
                {listBusy && (
                  <span className="inline-flex items-center gap-1.5">
                    <Spinner size={12} /> Updating…
                  </span>
                )}
              </div>
              <div style={{ opacity: listBusy ? 0.6 : 1 }}>
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
                        <td className="py-2" style={{ color: "var(--text-5)" }}>{new Date(e.createdAt).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              )}
              <div className="exp-total"><span className="ov-meta">Total</span><b className="ov-fig">{rupees(listResult.totalPaise)}</b></div>
              </div>
            </div>
          )}
        </div>

        <div className="exp-panel exp-budget">
          <h3 className="exp-title">Set category budget</h3>
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
        </div>

        <div className="exp-panel exp-status">
          <h3 className="exp-title">Check budget status</h3>
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
              <div className="mb-1 t-meta" style={{ color: "var(--text-5)" }}>
                {statusError ? "Last successful check: " : "Result for "}
                {statusShown}
              </div>
              {statusResult.noBudgetSet ? (
                <div style={{ color: "var(--text-6)" }}>No budget set for this category/period.</div>
              ) : (
                <>
                  <div className="exp-stats">
                    <div><span className="ov-meta">Spent</span><b className="ov-fig">{rupees(statusResult.spentPaise)}</b></div>
                    <div><span className="ov-meta">Budget</span><b className="ov-fig">{rupees(statusResult.budgetPaise)}</b></div>
                    <div><span className="ov-meta">Remaining</span><b className="ov-fig">{rupees(statusResult.remainingPaise)}</b></div>
                  </div>
                  {statusResult.budgetPaise !== null && statusResult.budgetPaise > 0 && (
                    <div className="ov-meter my-2" role="img" aria-label={`${rupees(statusResult.spentPaise)} spent of a ${rupees(statusResult.budgetPaise)} budget`}>
                      <i style={{ width: `${Math.min(100, (statusResult.spentPaise / statusResult.budgetPaise) * 100)}%`, background: statusResult.exceeded ? "var(--ov-bad)" : "var(--ov-brand)" }} />
                    </div>
                  )}
                  <Pill tone={statusResult.exceeded ? "bad" : "good"} icon={statusResult.exceeded ? "alert" : "check"}>
                    {statusResult.exceeded ? "Budget exceeded" : "Within budget"}
                  </Pill>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}
