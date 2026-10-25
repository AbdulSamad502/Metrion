"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { ApiError, apiFetch, type ImportComponent, type ImportDetail, type ImportRow } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";

const PAGE_SIZE = 50;

/** Display-only formatting of a persisted paise integer. No arithmetic beyond the unit shift. */
function money(paise: unknown): string {
  if (typeof paise !== "number") return "—";
  return `${paise < 0 ? "−" : ""}₹${(Math.abs(paise) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

type Column = { key: string; label: string; kind?: "money" | "date" | "id" | "number" };

/** Persisted columns, in reading order. A column is shown only if at least one row on the page has a
 * value for it — there are no empty decorative columns. (Cancellation/RTO status are not persisted
 * on a line, so they never appear here.) */
const SALES_COLUMNS: Column[] = [
  { key: "sourceRowNumber", label: "Row", kind: "number" },
  { key: "orderRef", label: "Order" },
  { key: "lineRef", label: "Line" },
  { key: "invoiceRef", label: "Invoice" },
  { key: "sku", label: "SKU" },
  { key: "itemTitle", label: "Product" },
  { key: "hsnSac", label: "HSN/SAC" },
  { key: "quantity", label: "Qty", kind: "number" },
  { key: "grossItemAmountPaise", label: "Gross amount", kind: "money" },
  { key: "taxableAmountPaise", label: "Taxable", kind: "money" },
  { key: "totalInvoiceAmountPaise", label: "Invoice total", kind: "money" },
  { key: "orderDate", label: "Order date", kind: "date" },
  { key: "dispatchDate", label: "Dispatched", kind: "date" },
  { key: "invoiceDate", label: "Invoiced", kind: "date" },
  { key: "documentType", label: "Document" },
  { key: "transactionType", label: "Transaction" },
  { key: "supplyType", label: "Supply" },
  { key: "paymentMethod", label: "Payment" },
  { key: "returnStatus", label: "Return status" },
  { key: "confidence", label: "Confidence" },
  { key: "salesLineId", label: "Sales line id", kind: "id" },
];

const SETTLEMENT_COLUMNS: Column[] = [
  { key: "sourceRowNumber", label: "Row", kind: "number" },
  { key: "orderRef", label: "Order" },
  { key: "lineRef", label: "Line" },
  { key: "settlementId", label: "Settlement" },
  { key: "grossSettlementAmountPaise", label: "Settled amount", kind: "money" },
  { key: "settlementDate", label: "Settled on", kind: "date" },
  { key: "documentType", label: "Document" },
  { key: "confidence", label: "Confidence" },
  { key: "settlementLineId", label: "Settlement line id", kind: "id" },
];

function hasValue(v: unknown): boolean {
  return v !== null && v !== undefined && v !== "";
}

function cell(col: Column, row: ImportRow) {
  const v = row[col.key];
  if (!hasValue(v)) return <span style={{ color: "var(--text-7)" }}>—</span>;
  if (col.kind === "money") return money(v);
  if (col.kind === "id") return <code title={String(v)}>{String(v).slice(0, 8)}</code>;
  if (col.kind === "date") return new Date(String(v)).toLocaleDateString("en-IN");
  return String(v);
}

function statusTone(status: string | null): "accent" | "warning" | "negative" | "neutral" {
  if (status === "VALIDATED") return "accent";
  if (status === "FAILED" || status === "MISMATCHED") return "negative";
  if (status === "PENDING" || status === "PARSING") return "warning";
  return "neutral";
}

export function categoryLabel(category: string): string {
  return { SETTLEMENT: "Settlement", TAX: "Tax", ORDER_STATUS: "Orders", ADVERTISING: "Advertising" }[category] ?? category;
}

/** The drawer. `reportFileId` null = closed. Opens on "Ingested data" — what Metrion persisted — and
 * never re-displays the browser's copy of the file. */
export function ImportViewer({
  reportFileId,
  onClose,
  getToken,
}: {
  reportFileId: string | null;
  onClose: () => void;
  getToken: () => Promise<string | null>;
}) {
  return (
    <DetailDrawer
      open={reportFileId !== null}
      onClose={onClose}
      size="wide"
      title="Import details"
      subtitle="What Metrion parsed and saved from this file"
    >
      {reportFileId && <ImportViewerBody key={reportFileId} reportFileId={reportFileId} getToken={getToken} />}
    </DetailDrawer>
  );
}

const TABS = [
  { id: "ingested", label: "Ingested data" },
  { id: "original", label: "Original CSV" },
  { id: "rejected", label: "Rejected" },
] as const;

function ImportViewerBody({ reportFileId, getToken }: { reportFileId: string; getToken: () => Promise<string | null> }) {
  const [tab, setTab] = useState<string>("ingested");
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<ImportDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    async (at: number) => {
      setLoading(true);
      setError(null);
      try {
        const token = await getToken();
        setDetail(await apiFetch<ImportDetail>(`/api/v1/cfo/imports/${reportFileId}?limit=${PAGE_SIZE}&offset=${at}`, token));
      } catch (e) {
        setError(e instanceof ApiError && e.status === 404 ? "This import no longer exists." : friendlyApiError(e, "Could not reach the backend"));
      } finally {
        setLoading(false);
      }
    },
    [getToken, reportFileId],
  );

  useEffect(() => {
    (async () => {
      await load(offset);
    })();
  }, [load, offset]);

  if (error && !detail) return <ErrorNotice message={error} onRetry={() => void load(offset)} />;
  if (!detail) return <LoadingState lines={6} label="Loading import" />;

  const c = detail.counts;
  const count = (n: number | null) => (n === null ? "—" : String(n));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="mt-eyebrow">
          {detail.marketplace} · {categoryLabel(detail.reportCategory)}
        </div>
        <div className="t-section mt-1 break-all" style={{ color: "var(--text-1)" }}>
          {detail.filename}
        </div>
        <div className="t-meta mt-1" style={{ color: "var(--text-5)" }}>
          {detail.adapter ? `${detail.adapter}` : "No ingestion run"} · uploaded {new Date(detail.uploadedAt).toLocaleString("en-IN")}
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          {detail.status && <StatusBadge tone={statusTone(detail.status)} dot>{detail.status.toLowerCase()}</StatusBadge>}
        </div>
      </div>

      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4" style={{ borderTop: "1px solid var(--border-subtle)", borderBottom: "1px solid var(--border-subtle)", padding: "14px 0" }}>
        {[
          ["Rows read", count(c.read)],
          ["Accepted", count(c.accepted)],
          ["Rejected", count(c.rejected)],
          ["Duplicates skipped", count(c.duplicate)],
        ].map(([k, v]) => (
          <div key={k}>
            <dt className="mt-eyebrow">{k}</dt>
            <dd className="t-metric m-0 mt-1" style={{ color: k === "Rejected" && c.rejected ? "var(--warning)" : "var(--text-1)" }}>
              {v}
            </dd>
          </div>
        ))}
      </dl>

      <Tabs
        tabs={TABS.map((t) => ({ ...t, count: t.id === "rejected" ? c.rejected ?? null : null }))}
        active={tab}
        onChange={setTab}
        label="Import views"
        idPrefix="imp"
      />

      <TabPanel id="ingested" active={tab} idPrefix="imp">
        <IngestedData detail={detail} loading={loading} error={error} offset={offset} onPage={setOffset} onRetry={() => void load(offset)} />
      </TabPanel>
      <TabPanel id="original" active={tab} idPrefix="imp">
        <div className="mt-panel">
          <div className="t-card-title" style={{ color: "var(--text-2)" }}>
            Original CSV
          </div>
          <div className="t-meta" style={{ color: "var(--text-5)" }}>
            What the seller uploaded
          </div>
          <p className="t-body mt-3" style={{ color: "var(--text-4)" }}>
            {detail.originalCsv.reason} The &ldquo;Ingested data&rdquo; tab shows what Metrion actually saved, which is what every
            figure is computed from.
          </p>
        </div>
      </TabPanel>
      <TabPanel id="rejected" active={tab} idPrefix="imp">
        <Rejected detail={detail} />
      </TabPanel>
    </div>
  );
}

function IngestedData({
  detail,
  loading,
  error,
  offset,
  onPage,
  onRetry,
}: {
  detail: ImportDetail;
  loading: boolean;
  error: string | null;
  offset: number;
  onPage: (offset: number) => void;
  onRetry: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const { rows, pagination } = detail;
  const columns = (detail.lineKind === "SETTLEMENT_LINE" ? SETTLEMENT_COLUMNS : SALES_COLUMNS).filter((col) =>
    rows.some((r) => hasValue(r[col.key])),
  );
  const rowId = (r: ImportRow) => String(r.salesLineId ?? r.settlementLineId);
  const hasComponents = rows.some((r) => r.components.length > 0);
  const from = pagination.total === 0 ? 0 : pagination.offset + 1;
  const to = pagination.offset + rows.length;

  if (pagination.total === 0) {
    return (
      <div className="mt-panel">
        <EmptyState
          compact
          icon="dot"
          title={detail.status === "VALIDATED" ? "No rows were saved" : "Nothing ingested"}
          description={
            detail.status === "VALIDATED"
              ? "The file was read but none of its rows were persisted — see the Rejected tab, or the counts above."
              : "This import has no persisted rows. It may have failed or not finished."
          }
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <ErrorNotice message={error} onRetry={onRetry} />}
      <div className="mt-table-wrap" aria-busy={loading} style={{ opacity: loading ? 0.6 : 1, transition: "opacity 0.15s ease" }}>
        <table className="mt-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} className={col.kind === "money" || col.kind === "number" ? "text-right" : undefined}>
                  {col.label}
                </th>
              ))}
              {hasComponents && <th>Fees &amp; taxes</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const id = rowId(r);
              const expanded = open === id;
              return (
                <Fragment key={id}>
                  <tr
                    data-clickable="true"
                    data-selected={expanded}
                    tabIndex={0}
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpen(expanded ? null : id);
                      }
                    }}
                  >
                    {columns.map((col, i) => (
                      <td key={col.key} className={col.kind === "money" || col.kind === "number" ? "text-right" : undefined}>
                        {i === 0 && <span className="sr-only">{expanded ? "Collapse row details. " : "Expand row details. "}</span>}
                        {cell(col, r)}
                      </td>
                    ))}
                    {hasComponents && (
                      <td style={{ color: "var(--text-5)" }}>{r.components.length > 0 ? `${r.components.length} component${r.components.length === 1 ? "" : "s"}` : "—"}</td>
                    )}
                  </tr>
                  {expanded && (
                    <tr>
                      <td colSpan={columns.length + (hasComponents ? 1 : 0)} style={{ padding: 0 }}>
                        <ComponentDetail components={r.components} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="t-meta" style={{ color: "var(--text-5)" }} aria-live="polite">
          Showing {from}–{to} of {pagination.total} saved {pagination.total === 1 ? "row" : "rows"}
        </div>
        <div className="flex gap-2">
          <PageButton disabled={offset === 0 || loading} onClick={() => onPage(Math.max(0, offset - pagination.limit))}>
            Previous
          </PageButton>
          <PageButton disabled={to >= pagination.total || loading} onClick={() => onPage(offset + pagination.limit)}>
            Next
          </PageButton>
        </div>
      </div>
    </div>
  );
}

function PageButton({ disabled, onClick, children }: { disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="mt-btn mt-focus t-button rounded-lg px-3.5 py-2 disabled:cursor-not-allowed disabled:opacity-40"
      style={{ color: "var(--text-3)", border: "1px solid var(--glass-border-hover)", background: "var(--glass-bg)" }}
    >
      {children}
    </button>
  );
}

function ComponentDetail({ components }: { components: ImportComponent[] }) {
  if (components.length === 0) {
    return (
      <div className="t-meta px-4 py-3" style={{ color: "var(--text-5)", background: "var(--glass-bg)" }}>
        No fee, tax or discount components were persisted for this row.
      </div>
    );
  }
  return (
    <div className="px-4 py-3" style={{ background: "var(--glass-bg)" }}>
      <div className="mt-eyebrow mb-2">Persisted components</div>
      <div className="mt-table-wrap" style={{ border: 0, background: "transparent" }}>
        <table className="mt-table">
          <thead>
            <tr>
              <th>Kind</th>
              <th>Code</th>
              <th>Side</th>
              <th className="text-right">Amount</th>
              <th className="text-right">Tax</th>
              <th className="text-right">Rate</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c, i) => (
              <tr key={i}>
                <td>{c.kind.toLowerCase()}</td>
                <td style={{ fontWeight: 400 }}>{c.code}</td>
                <td style={{ fontWeight: 400 }}>{c.side.toLowerCase()}</td>
                <td className="text-right" style={{ fontWeight: 400 }}>{money(c.amountPaise)}</td>
                <td className="text-right" style={{ fontWeight: 400 }}>{c.taxAmountPaise === null ? "—" : money(c.taxAmountPaise)}</td>
                <td className="text-right" style={{ fontWeight: 400 }}>{c.ratePct === null ? "—" : `${c.ratePct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Rejected({ detail }: { detail: ImportDetail }) {
  const { rejected } = detail;
  if (rejected.findings.length > 0) {
    return (
      <div className="flex flex-col gap-3">
        <p className="t-body-sm" style={{ color: "var(--text-4)" }}>
          Recorded diagnostics for this import ({rejected.findingsTotal}). Shown exactly as saved at ingestion.
        </p>
        <div className="mt-table-wrap">
          <table className="mt-table">
            <thead>
              <tr>
                <th className="text-right">Row</th>
                <th>Rule</th>
                <th>Severity</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rejected.findings.map((f, i) => (
                <tr key={i}>
                  <td className="text-right">{f.sourceRowNumber ?? "—"}</td>
                  <td style={{ fontWeight: 400 }}>{f.ruleId}</td>
                  <td>
                    <StatusBadge tone={f.severity === "ERROR" ? "negative" : "warning"}>{f.severity.toLowerCase()}</StatusBadge>
                  </td>
                  <td style={{ fontWeight: 400, whiteSpace: "normal" }}>{f.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
  const n = rejected.count ?? 0;
  return (
    <div className="mt-panel">
      <EmptyState
        compact
        icon={n > 0 ? "dot" : "check"}
        title={n > 0 ? `${n} ${n === 1 ? "row was" : "rows were"} rejected` : "No rows were rejected"}
        description={
          n > 0
            ? "Metrion recorded how many rows were rejected, but did not keep the per-row reason for this import, so none is shown rather than guessing."
            : "Every row Metrion read from this file passed validation."
        }
      />
    </div>
  );
}
