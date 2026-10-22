import { MARKETPLACE_FILTERS, type FilterParams, type MarketplaceFilter } from "./types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SKU_MAX = 60;

export const DEFAULT_FILTERS: FilterParams = { from: null, to: null, marketplace: "ALL", sku: "" };

/** Filters live in the URL (`?from=&to=&marketplace=&sku=`) so a view is shareable and reload-safe. Anything that is not an allow-listed value is dropped, never passed on. */
export function parseFilters(search: string): FilterParams {
  const q = new URLSearchParams(search);
  const date = (k: string): string | null => {
    const v = q.get(k);
    return v !== null && ISO_DATE.test(v) ? v : null;
  };
  const mp = (q.get("marketplace") ?? "ALL").toUpperCase();
  const marketplace: MarketplaceFilter = (MARKETPLACE_FILTERS as readonly string[]).includes(mp) ? (mp as MarketplaceFilter) : "ALL";
  let from = date("from");
  let to = date("to");
  if (from && to && to < from) {
    from = null;
    to = null; // an inverted range is not a filter
  }
  return { from, to, marketplace, sku: (q.get("sku") ?? "").trim().slice(0, SKU_MAX) };
}

export function serializeFilters(f: FilterParams): string {
  const q = new URLSearchParams();
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  if (f.marketplace !== "ALL") q.set("marketplace", f.marketplace);
  if (f.sku.trim()) q.set("sku", f.sku.trim().slice(0, SKU_MAX));
  return q.toString();
}

/** The query string a data route receives for these filters (plus paging/sort when given). */
export function apiQuery(f: FilterParams, extra?: { page?: number; pageSize?: number; sort?: string; dir?: "asc" | "desc" }): string {
  const q = new URLSearchParams(serializeFilters(f));
  if (extra?.page !== undefined) q.set("page", String(extra.page));
  if (extra?.pageSize !== undefined) q.set("pageSize", String(extra.pageSize));
  if (extra?.sort) q.set("sort", extra.sort);
  if (extra?.dir) q.set("dir", extra.dir);
  return q.toString();
}
