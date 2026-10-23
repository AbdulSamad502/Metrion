"use client";

import { useState } from "react";
import { TrendChart } from "@/components/cfo/v2/charts/TrendChart";
import { FilterBar } from "@/components/cfo/v2/filters/FilterBar";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { DataTable, FigureCell, type Column } from "@/components/cfo/v2/tables/DataTable";
import { ExportButton } from "@/components/cfo/v2/tables/ExportButton";
import { FigureView } from "@/components/cfo/v2/trust/FigureView";
import {
  periodQuery,
  type BridgeResponse,
  type CostBreakdownResponse,
  type MarketplaceRow,
  type MarketplacesResponse,
  type Period,
  type SkuRow,
  type SkusResponse,
  type TrendResponse,
} from "@/lib/cfoV2/dashboard";
import type { SortDir } from "@/lib/cfoV2/types";
import { useCfoData } from "@/lib/cfoV2/useCfoData";
import { useCfoFilters } from "@/lib/cfoV2/useCfoFilters";

const MP_COLUMNS: Column<MarketplaceRow>[] = [
  { key: "marketplace", header: "Marketplace", render: (r) => r.marketplace },
  { key: "grossSales", header: "Gross Sales", render: (r) => <FigureCell cell={r.grossSales} /> },
  { key: "nrr", header: "Net Realized Revenue", render: (r) => <FigureCell cell={r.nrr} /> },
  { key: "contributionProfit", header: "Contribution Profit", render: (r) => <FigureCell cell={r.contributionProfit} /> },
  { key: "margin", header: "Contribution Margin", render: (r) => <FigureCell cell={r.margin} /> },
];
const SKU_COLUMNS: Column<SkuRow>[] = [
  { key: "key", header: "SKU", sortable: true, render: (r) => r.sku },
  { key: "grossSales", header: "Gross Sales", sortable: true, render: (r) => <FigureCell cell={r.grossSales} /> },
  { key: "nrr", header: "Net Realized Revenue", sortable: true, render: (r) => <FigureCell cell={r.nrr} /> },
  { key: "contributionProfit", header: "Contribution Profit", sortable: true, render: (r) => <FigureCell cell={r.contributionProfit} /> },
];

/** Profitability: marketplace and SKU tables (the server sorts and pages), the Contribution Profit trend with its table, and the profit bridge between two periods. */
export function ProfitabilityTab({ period }: { period: Period }) {
  const [filters, setFilters] = useCfoFilters();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; dir: SortDir }>({ key: "contributionProfit", dir: "desc" });
  const [cmp, setCmp] = useState<{ start: string; end: string }>({ start: "", end: "" });
  const base = periodQuery(filters, period);

  const mp = useCfoData<MarketplacesResponse>("/profitability/marketplaces", base);
  const skuQuery = `${base}&${new URLSearchParams({ page: String(page), page_size: "25", sort: sort.key, dir: sort.dir, sku: filters.sku }).toString()}`;
  const skus = useCfoData<SkusResponse>("/profitability/skus", skuQuery);
  const trend = useCfoData<TrendResponse>("/profitability/trend", base);
  const breakdown = useCfoData<CostBreakdownResponse>("/profitability/cost-breakdown", base);
  const bridge = useCfoData<BridgeResponse>(cmp.start && cmp.end ? "/profitability/bridge" : null, `${base}&compare_start=${cmp.start}&compare_end=${cmp.end}`);

  return (
    <div className="flex flex-col gap-8">
      <FilterBar
        filters={filters}
        onChange={(n) => {
          setPage(1);
          setFilters(n);
        }}
      />
      <section aria-label="By marketplace" className="flex flex-col gap-3">
        <h3 className="t-label">By marketplace</h3>
        <SectionState state={mp} title="marketplace figures">
          {(d) => (
            <>
              <DataTable columns={MP_COLUMNS} rows={d.items} rowKey={(r) => r.key} page={1} total={d.items.length} pageCount={1} onSort={() => {}} onPage={() => {}} caption="Profit by marketplace" />
              {d.coverage.some((c) => !c.included) && (
                <p className="t-meta" style={{ color: "var(--text-5)" }}>
                  Marketplaces shown as not available are left out of totals because their data is incomplete; the Overview lists what is missing.
                </p>
              )}
            </>
          )}
        </SectionState>
      </section>
      <section aria-label="Cost breakdown" className="flex flex-col gap-3">
        <h3 className="t-label">From Net Realized Revenue to Contribution Profit</h3>
        <SectionState state={breakdown} title="the cost breakdown">
          {(d) => (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {d.figures.map((f) => (
                <FigureView key={f.label} figure={f} />
              ))}
            </div>
          )}
        </SectionState>
      </section>
      <section aria-label="Trend" className="flex flex-col gap-3">
        <SectionState state={trend} title="the trend">
          {(d) => <TrendChart title="Contribution Profit by month" points={d.points} />}
        </SectionState>
      </section>
      <section aria-label="By SKU" className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="t-label">By SKU</h3>
          <ExportButton path="/api/v1/cfo/profitability/skus" query={base} format="csv" filename="sku-profit" label="Export CSV" />
        </div>
        <SectionState state={skus} title="SKU figures">
          {(d) => (
            <DataTable
              columns={SKU_COLUMNS}
              rows={d.items}
              rowKey={(r) => r.key}
              page={d.page}
              total={d.total}
              pageCount={d.pageCount}
              sort={sort.key}
              dir={sort.dir}
              onSort={(key, dir) => {
                setPage(1);
                setSort({ key, dir });
              }}
              onPage={setPage}
              caption="Profit by SKU"
            />
          )}
        </SectionState>
      </section>
      <section aria-label="Profit bridge" className="flex flex-col gap-3">
        <h3 className="t-label">What changed in Contribution Profit</h3>
        <form className="flex flex-wrap items-end gap-3" aria-label="Comparison period" onSubmit={(e) => e.preventDefault()}>
          <label className="flex flex-col gap-1 t-meta">
            Compare against from
            <input type="date" value={cmp.start} onChange={(e) => setCmp((c) => ({ ...c, start: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1 t-meta">
            to
            <input type="date" value={cmp.end} onChange={(e) => setCmp((c) => ({ ...c, end: e.target.value }))} />
          </label>
        </form>
        {cmp.start && cmp.end ? (
          <SectionState state={bridge} title="the profit bridge">
            {(d) =>
              d.bridge ? (
                <>
                  <ul className="list-disc pl-5 t-body">
                    {d.bridge.drivers.map((x) => (
                      <li key={x.metricId}>
                        {x.metricId.replaceAll("_", " ").toLowerCase()}: {x.deltaDisplay}
                      </li>
                    ))}
                    <li>Other: {d.bridge.otherDisplay}</li>
                  </ul>
                  <p className="t-body">Total change: {d.bridge.deltaDisplay}</p>
                  {!d.reconciles && <p role="alert">These drivers do not add up to the total change, so treat this bridge as unconfirmed.</p>}
                </>
              ) : (
                <p className="t-body">{(d.reasons ?? []).filter(Boolean).join("; ") || "A bridge needs both periods to have complete data."}</p>
              )
            }
          </SectionState>
        ) : (
          <p className="t-meta" style={{ color: "var(--text-5)" }}>
            Choose a second period to see what moved Contribution Profit between the two.
          </p>
        )}
      </section>
    </div>
  );
}
