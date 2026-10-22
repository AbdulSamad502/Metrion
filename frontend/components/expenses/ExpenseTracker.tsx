"use client";

import { useCallback, useEffect, useState } from "react";
import { Section } from "@/components/ui/Section";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { LoadingState } from "@/components/ui/LoadingState";
import { ErrorText, Field, SubmitButton, TextInput } from "@/components/cfo/primitives";
import { friendlyApiError } from "@/lib/apiErrors";
import { useHashTab } from "@/lib/useHashTab";
import {
  loadList, loadMeta, loadSummary, post,
  type ExpenseListResponse, type ExpenseRecord, type Getter, type LedgerMeta, type ListFilters, type PaymentStatus, type SummaryResponse,
} from "@/lib/expenseLedger";
import { ExpenseForm, RefundPanel, VoidPanel } from "./ExpenseForm";
import { ExpenseTable, Overview, ReviewQueue } from "./ExpenseViews";
import { AssignPanel, ImportExportPanel, RecurringPanel } from "./ExpenseTools";

const TABS = ["overview", "expenses", "review", "add", "recurring", "import"] as const;

/** The default period is the current calendar month: dates only, no money. */
function currentMonth(): { start: string; end: string } {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const pad = (n: number) => String(n).padStart(2, "0");
  const last = new Date(y, m + 1, 0).getDate();
  return { start: `${y}-${pad(m + 1)}-01`, end: `${y}-${pad(m + 1)}-${pad(last)}` };
}

/** The Expense Tracker dashboard (route /dashboard/cfo/expenses). It only displays and submits: every total is produced by the backend's engine feed and carries its
 * result reference (AC17); the review state and the payment status are separate fields; edits are linked corrections and removals are voids, never deletes. */
export function ExpenseTracker({ getToken }: { getToken: Getter }) {
  const [tab, setTab] = useHashTab(TABS, "overview");
  const [initial] = useState(currentMonth);
  const [periodStart, setPeriodStart] = useState(initial.start);
  const [periodEnd, setPeriodEnd] = useState(initial.end);
  const [meta, setMeta] = useState<LedgerMeta | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [list, setList] = useState<ExpenseListResponse | null>(null);
  const [filters, setFilters] = useState<ListFilters>({});
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [correcting, setCorrecting] = useState<ExpenseRecord | null>(null);
  const [voiding, setVoiding] = useState<ExpenseRecord | null>(null);
  const [refunding, setRefunding] = useState<ExpenseRecord | null>(null);
  const [assigning, setAssigning] = useState<ExpenseRecord | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reloadSummary = useCallback(async () => {
    try {
      setSummary(await loadSummary(getToken, periodStart, periodEnd));
      setError(null);
    } catch (e) {
      setError(friendlyApiError(e, "Could not load the expense totals"));
    }
  }, [getToken, periodStart, periodEnd]);

  const reloadList = useCallback(async () => {
    try {
      setList(await loadList(getToken, filters));
    } catch (e) {
      setError(friendlyApiError(e, "Could not load the expenses"));
    }
  }, [getToken, filters]);

  useEffect(() => {
    (async () => {
      try {
        setMeta(await loadMeta(getToken));
      } catch (e) {
        setError(friendlyApiError(e, "Could not load the expense tracker"));
      }
    })();
  }, [getToken]);
  useEffect(() => {
    (async () => {
      await reloadSummary();
    })();
  }, [reloadSummary]);
  useEffect(() => {
    (async () => {
      await reloadList();
    })();
  }, [reloadList]);

  const refresh = async () => { await Promise.all([reloadSummary(), reloadList()]); };

  const run = async (id: string, fn: () => Promise<unknown>, failure: string) => {
    setBusyId(id);
    setActionError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setActionError(friendlyApiError(e, failure));
    } finally {
      setBusyId(null);
    }
  };

  if (!meta && !error) return <LoadingState lines={3} label="Loading the expense tracker" />;

  const queue = summary?.reviewQueue.items.length ?? 0;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "expenses", label: "Expenses" },
    { id: "review", label: "Review queue", count: queue },
    { id: "add", label: correcting ? "Correct an expense" : "Add expense" },
    { id: "recurring", label: "Recurring" },
    { id: "import", label: "Import & export" },
  ];

  return (
    <div className="mt-content flex flex-col gap-6">
      <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-3">
        <Field label="Period from"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
        <Field label="Period to"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
        <SubmitButton onClick={refresh} busy={false} label="Refresh" busyLabel="Refreshing…" />
      </div>
      <ErrorText>{error}</ErrorText>
      <ErrorText>{actionError}</ErrorText>
      <Tabs tabs={tabs} active={tab} onChange={setTab} label="Expense tracker" idPrefix="exp" />

      <TabPanel id="overview" active={tab} idPrefix="exp">
        {summary ? <Overview summary={summary} /> : <LoadingState lines={3} label="Loading totals" />}
      </TabPanel>

      <TabPanel id="expenses" active={tab} idPrefix="exp">
        {meta && list ? (
          <>
            <ExpenseTable
              getToken={getToken} records={list.records} filters={filters} meta={meta} onFilters={setFilters}
              onCorrect={(r) => { setCorrecting(r); setTab("add"); }}
              onRefund={(r) => { setRefunding(r); setVoiding(null); }}
              onVoid={(r) => { setVoiding(r); setRefunding(null); setAssigning(null); }}
              onAssign={(r) => { setAssigning(r); setVoiding(null); setRefunding(null); }}
              onPayment={(r, status: PaymentStatus) => run(r.id, () => post(getToken, `/${r.id}/payment`, { status, ...(status === "paid" ? { paid_amount_paise: String(r.amountPaise) } : {}) }), "Could not change the payment status")}
            />
            {voiding && <VoidPanel getToken={getToken} record={voiding} onCancel={() => setVoiding(null)} onDone={async () => { setVoiding(null); await refresh(); }} />}
            {assigning && <AssignPanel getToken={getToken} record={assigning} onCancel={() => setAssigning(null)} onDone={async () => { setAssigning(null); await refresh(); }} />}
            {refunding && <RefundPanel getToken={getToken} record={refunding} onCancel={() => setRefunding(null)} onDone={async () => { setRefunding(null); await refresh(); }} />}
          </>
        ) : <LoadingState lines={3} label="Loading expenses" />}
      </TabPanel>

      <TabPanel id="review" active={tab} idPrefix="exp">
        {summary ? (
          <Section title="Items to review" hint="Entries waiting for review are not in the total until you confirm them. An entry whose SKU is not found stays in the total; only its SKU allocation is pending.">
            <ReviewQueue summary={summary} busyId={busyId} onConfirm={(id) => run(id, () => post(getToken, `/${id}/review`, { state: "confirmed" }), "Could not confirm the expense")} />
          </Section>
        ) : <LoadingState lines={3} label="Loading the review queue" />}
      </TabPanel>

      <TabPanel id="recurring" active={tab} idPrefix="exp">
        {meta ? <RecurringPanel getToken={getToken} meta={meta} onChanged={refresh} /> : <LoadingState lines={3} label="Loading recurring entries" />}
      </TabPanel>

      <TabPanel id="import" active={tab} idPrefix="exp">
        <ImportExportPanel getToken={getToken} onChanged={refresh} />
      </TabPanel>

      <TabPanel id="add" active={tab} idPrefix="exp">
        {meta && (
          <Section title={correcting ? "Correct an expense" : "Add an expense"} hint="Amounts are in rupees. A correction keeps the original on record, voided.">
            <ExpenseForm
              key={correcting?.id ?? "new"} getToken={getToken} meta={meta} correcting={correcting}
              onCancel={() => { setCorrecting(null); setTab("expenses"); }}
              onSaved={async () => { setCorrecting(null); await refresh(); setTab("expenses"); }}
            />
          </Section>
        )}
      </TabPanel>
    </div>
  );
}
