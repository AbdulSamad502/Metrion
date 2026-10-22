"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { FilterBar } from "@/components/cfo/v2/filters/FilterBar";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { DataTable, FigureCell, type Column } from "@/components/cfo/v2/tables/DataTable";
import { FigureView } from "@/components/cfo/v2/trust/FigureView";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { API_BASE, apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { periodQuery, type CashResponse, type PayableRow, type PayablesResponse, type Period } from "@/lib/cfoV2/dashboard";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";
import { useCfoFilters } from "@/lib/cfoV2/useCfoFilters";

const PAYABLE_COLUMNS: Column<PayableRow>[] = [
  { key: "supplier", header: "Supplier", render: (r) => r.supplierRef ?? "—" },
  { key: "po", header: "PO", render: (r) => r.poRef ?? "—" },
  { key: "due", header: "Due", render: (r) => r.dueDate ?? "No date" },
  { key: "amount", header: "Amount", render: (r) => <FigureCell cell={r.amount} /> },
];

/** Cash & Tax: expected settlements and your payables (an estimate from your own settlement history, never a bank balance), the CA export pack, and where GST stands. */
export function CashTaxTab({ period }: { period: Period }) {
  const { getToken } = useAuth();
  const canAdjust = useCanAdjust();
  const [filters, setFilters] = useCfoFilters();
  const cash = useCfoData<CashResponse>("/cash/expected-receipts", periodQuery(filters, period));
  const payables = useCfoData<PayablesResponse>("/cash/payables", "");
  const [form, setForm] = useState({ amount: "", due: "", supplier: "" });
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"xlsx" | "zip" | null>(null);

  const addPayable = async () => {
    setError(null);
    try {
      await apiFetch("/api/v1/cfo/payables", await getToken(), {
        method: "POST",
        body: JSON.stringify({ amount_rupees: form.amount.trim(), due_date: form.due || null, supplier_ref: form.supplier.trim() || null }),
      });
      setForm({ amount: "", due: "", supplier: "" });
      payables.reload();
      cash.reload();
    } catch (e) {
      setError(friendlyApiError(e, "The payable could not be saved"));
    }
  };

  const download = async (format: "xlsx" | "zip") => {
    setExporting(format);
    setError(null);
    try {
      const f = filters.from ?? period.start;
      const t = filters.to ?? period.end;
      const res = await fetch(`${API_BASE}/api/v1/cfo/ca-export?period_start=${f}&period_end=${t}&as_of_date=${t}&format=${format}`, { headers: { Authorization: `Bearer ${await getToken()}` } });
      if (!res.ok) throw new Error(`Request failed with ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `metrion-ca-pack-${f}-to-${t}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(friendlyApiError(e, "The pack could not be created"));
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <FilterBar filters={filters} onChange={setFilters} />
      {error && <ErrorNotice message={error} />}
      <section aria-label="Expected settlements" className="flex flex-col gap-3">
        <h3 className="t-label">Expected settlements and what you owe</h3>
        <SectionState state={cash} title="expected settlements">
          {(d) => (
            <>
              <p className="t-body">{d.note}</p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {d.figures.map((f, i) => (
                  <FigureView key={`${f.label}-${i}`} figure={f} />
                ))}
              </div>
              {d.dataRequests.length > 0 && (
                <ul className="list-disc pl-5 t-body">
                  {d.dataRequests.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </SectionState>
      </section>
      <section aria-label="Payables" className="flex flex-col gap-3">
        <h3 className="t-label">Payables you entered</h3>
        <SectionState state={payables} title="payables">
          {(d) => <DataTable columns={PAYABLE_COLUMNS} rows={d.items} rowKey={(r) => r.id} page={1} total={d.items.length} pageCount={1} onSort={() => {}} onPage={() => {}} caption="Payables" emptyText="No payables entered yet." />}
        </SectionState>
        {canAdjust && (
          <form
            aria-label="Add a payable"
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void addPayable();
            }}
          >
            <label className="flex flex-col gap-1 t-meta">
              Amount in rupees
              <input inputMode="decimal" value={form.amount} onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))} placeholder="12500.50" />
            </label>
            <label className="flex flex-col gap-1 t-meta">
              Due date
              <input type="date" value={form.due} onChange={(e) => setForm((f) => ({ ...f, due: e.target.value }))} />
            </label>
            <label className="flex flex-col gap-1 t-meta">
              Supplier
              <input value={form.supplier} maxLength={120} onChange={(e) => setForm((f) => ({ ...f, supplier: e.target.value }))} />
            </label>
            <button type="submit" disabled={!form.amount.trim()}>
              Add payable
            </button>
          </form>
        )}
      </section>
      <section aria-label="Tax" className="flex flex-col gap-3">
        <h3 className="t-label">GST (indicative)</h3>
        <p className="t-body">
          GST treatment is not confirmed yet, so no GST or tax-asset figure is shown here. The GST tools under Tools are informational only; check due dates and filings with your CA.
        </p>
      </section>
      <section aria-label="CA export" className="flex flex-col gap-3">
        <h3 className="t-label">Pack for your CA</h3>
        <p className="t-body">Prepared material for the period above: figures with their sources, everything excluded or unavailable with reasons, and open questions. It is not a return and files nothing.</p>
        <span className="flex gap-3">
          <button type="button" disabled={exporting !== null} onClick={() => download("xlsx")}>
            {exporting === "xlsx" ? "Preparing…" : "Download workbook (.xlsx)"}
          </button>
          <button type="button" disabled={exporting !== null} onClick={() => download("zip")}>
            {exporting === "zip" ? "Preparing…" : "Download CSV files (.zip)"}
          </button>
        </span>
      </section>
    </div>
  );
}
