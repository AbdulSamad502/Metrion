"use client";

import { SectionState } from "@/components/cfo/v2/SectionState";
import { DataTable, FigureCell, type Column } from "@/components/cfo/v2/tables/DataTable";
import { periodQuery, type ExpenseSummaryResponse, type ExpenseSummaryRow, type HealthResponse, type LeakResponse, type Period } from "@/lib/cfoV2/dashboard";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";
import type { FilterParams } from "@/lib/cfoV2/types";

const EXPENSE_COLUMNS: Column<ExpenseSummaryRow>[] = [
  { key: "category", header: "Category", render: (r) => r.category },
  { key: "class", header: "Kind", render: (r) => r.expenseClass.replaceAll("_", " ").toLowerCase() },
  { key: "amount", header: "Amount", render: (r) => <FigureCell cell={r.amount} /> },
];

/** The financial health band: a classification of three stored figures against the configured thresholds. Without enough figures it says why and shows no band. */
export function HealthBand({ filters, period }: { filters: FilterParams; period: Period }) {
  const state = useCfoData<HealthResponse>("/overview/health", periodQuery(filters, period));
  return (
    <section aria-label="Financial health" className="flex flex-col gap-3">
      <h3 className="t-label">Financial health</h3>
      <SectionState state={state} title="financial health">
        {(d) =>
          d.overallBand ? (
            <>
              <p className="t-body">
                Overall: <strong>{d.overallBand}</strong>
              </p>
              <ul className="list-disc pl-5 t-body">
                {d.perMetric.map((m) => (
                  <li key={m.label}>
                    {m.label}: {m.band}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="t-body">No health band for this period: {d.unavailableReason ?? "the figures it needs are not available yet"}.</p>
          )
        }
      </SectionState>
    </section>
  );
}

/** The few discrepancies that matter most, ordered by how soon their claim window closes. Seller-reported status only. */
export function LeakPreview() {
  const state = useCfoData<LeakResponse>("/leak/findings", "page=1&page_size=3");
  return (
    <section aria-label="Top discrepancies" className="flex flex-col gap-3">
      <h3 className="t-label">Discrepancies to review first</h3>
      <SectionState state={state} title="discrepancies">
        {(d) =>
          d.items.length === 0 ? (
            <p className="t-body">No discrepancies identified from the files you have uploaded.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {d.items.map((r) => (
                <li key={r.id} className="t-body">
                  {r.category.replaceAll("_", " ").toLowerCase()} · {r.marketplace}
                  {r.withheld ? " — provisional, withheld" : <> · <FigureCell cell={r.amount} /></>}
                </li>
              ))}
            </ul>
          )
        }
      </SectionState>
    </section>
  );
}

/** Business expenses by category from the ledger (the owner account is never in this list). */
export function ExpensePools({ filters, period }: { filters: FilterParams; period: Period }) {
  const state = useCfoData<ExpenseSummaryResponse>("/expenses/summary", periodQuery({ ...filters, marketplace: "ALL" }, period));
  return (
    <section aria-label="Expenses by category" className="flex flex-col gap-3">
      <h3 className="t-label">Expenses by category</h3>
      <SectionState state={state} title="expenses">
        {(d) => <DataTable columns={EXPENSE_COLUMNS} rows={d.items} rowKey={(r) => `${r.category}|${r.expenseClass}`} page={1} total={d.items.length} pageCount={1} onSort={() => {}} onPage={() => {}} caption="Expenses by category" emptyText="No expenses recorded for this period." />}
      </SectionState>
    </section>
  );
}

/** The owner account: drawings only, separate from business expenses and in no profit figure. Shown only to someone allowed to change financial data. */
export function OwnerAccount({ filters, period }: { filters: FilterParams; period: Period }) {
  const canAdjust = useCanAdjust();
  const state = useCfoData<ExpenseSummaryResponse>(canAdjust ? "/expenses/owner-account" : null, periodQuery({ ...filters, marketplace: "ALL" }, period));
  if (!canAdjust) return null;
  return (
    <section aria-label="Owner account" className="flex flex-col gap-3">
      <h3 className="t-label">Owner account</h3>
      <SectionState state={state} title="the owner account">
        {(d) => (
          <>
            {d.note && <p className="t-meta" style={{ color: "var(--text-5)" }}>{d.note}</p>}
            <DataTable columns={EXPENSE_COLUMNS} rows={d.items} rowKey={(r) => `${r.category}|${r.expenseClass}`} page={1} total={d.items.length} pageCount={1} onSort={() => {}} onPage={() => {}} caption="Owner account" emptyText="No owner drawings recorded for this period." />
          </>
        )}
      </SectionState>
    </section>
  );
}

