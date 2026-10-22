"use client";

import type { ReactNode } from "react";
import { CompletenessBadge } from "@/components/cfo/v2/trust/CompletenessBadge";
import type { CellFigure, SortDir } from "@/lib/cfoV2/types";

export type Column<T> = { key: string; header: string; sortable?: boolean; render: (row: T) => ReactNode };

/** A cell that holds a server-formatted figure. Unavailable renders "—" and a text reason marker, never 0; anything not COMPLETE carries its badge. */
export function FigureCell({ cell }: { cell: CellFigure }) {
  if (cell.display === null || cell.status === "UNAVAILABLE") return <span aria-label="not available">—</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {cell.display}
      {cell.status !== "COMPLETE" && <CompletenessBadge completeness={cell.status} />}
    </span>
  );
}

/** A server-paginated, server-sorted table. It never sorts or slices rows itself: clicking a header or a pager button only asks the parent to request another
 * page. The current sort is exposed with `aria-sort`; the pager shows the server's totals. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  page,
  total,
  pageCount,
  sort,
  dir,
  onSort,
  onPage,
  caption,
  emptyText = "Nothing to show for these filters.",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  page: number;
  total: number;
  pageCount: number; // from the server's page envelope; the table does no arithmetic
  sort?: string;
  dir?: SortDir;
  onSort: (key: string, dir: SortDir) => void;
  onPage: (page: number) => void;
  caption: string;
  emptyText?: string;
}) {
  const lastPage = pageCount;
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="w-full t-body">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort === c.key;
                return (
                  <th key={c.key} scope="col" className="px-3 py-2 text-left" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : c.sortable ? "none" : undefined}>
                    {c.sortable ? (
                      <button type="button" onClick={() => onSort(c.key, active && dir === "desc" ? "asc" : "desc")}>
                        {c.header}
                        {active ? (dir === "asc" ? " ▲" : " ▼") : ""}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center" style={{ color: "var(--text-5)" }}>
                  {emptyText}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={rowKey(r)}>
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-2">
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <nav className="flex items-center justify-between t-meta" aria-label={`${caption} pages`}>
        <span>
          Page {page} of {lastPage} · {total} rows
        </span>
        <span className="flex gap-2">
          <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            Previous
          </button>
          <button type="button" disabled={page >= lastPage} onClick={() => onPage(page + 1)}>
            Next
          </button>
        </span>
      </nav>
    </div>
  );
}
