"use client";

import { MARKETPLACE_FILTERS, type FilterParams, type MarketplaceFilter } from "@/lib/cfoV2/types";

const MP_LABEL: Record<MarketplaceFilter, string> = { ALL: "All marketplaces", AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };

/** Date range, marketplace and SKU search. A controlled view over `useCfoFilters`; the filters it produces are validated again by the hook and, finally, by the server. */
export function FilterBar({ filters, onChange }: { filters: FilterParams; onChange: (next: Partial<FilterParams>) => void }) {
  return (
    <form className="flex flex-wrap items-end gap-3" aria-label="Filters" onSubmit={(e) => e.preventDefault()}>
      <label className="flex flex-col gap-1 t-meta">
        From
        <input type="date" value={filters.from ?? ""} max={filters.to ?? undefined} onChange={(e) => onChange({ from: e.target.value || null })} />
      </label>
      <label className="flex flex-col gap-1 t-meta">
        To
        <input type="date" value={filters.to ?? ""} min={filters.from ?? undefined} onChange={(e) => onChange({ to: e.target.value || null })} />
      </label>
      <label className="flex flex-col gap-1 t-meta">
        Marketplace
        <select value={filters.marketplace} onChange={(e) => onChange({ marketplace: e.target.value as MarketplaceFilter })}>
          {MARKETPLACE_FILTERS.map((m) => (
            <option key={m} value={m}>
              {MP_LABEL[m]}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 t-meta">
        SKU
        <input type="search" value={filters.sku} maxLength={60} placeholder="Search SKU" onChange={(e) => onChange({ sku: e.target.value })} />
      </label>
    </form>
  );
}
