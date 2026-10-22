"use client";

import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricCard } from "@/components/ui/MetricCard";
import { Section } from "@/components/ui/Section";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import { Field, SelectInput, TextInput } from "@/components/cfo/primitives";
import {
  COST_CLASS_LABEL, PAYMENT_LABEL, REVIEW_LABEL, REVIEW_REASON_LABEL, money,
  type ExpenseRecord, type LedgerMeta, type ListFilters, type PaymentStatus, type ReviewState, type SummaryResponse,
} from "@/lib/expenseLedger";

const REVIEW_TONE: Record<ReviewState, Tone> = { draft: "neutral", pending_review: "warning", confirmed: "accent", voided: "negative" };
const PAYMENT_TONE: Record<PaymentStatus, Tone> = { unpaid: "warning", partially_paid: "info", paid: "accent", unknown: "neutral" };

/** The two statuses are separate fields: the review state decides whether an expense counts; the payment status never changes any margin. */
export function ReviewBadge({ state }: { state: ReviewState }) {
  return <span data-testid="review-state"><StatusBadge tone={REVIEW_TONE[state]} dot>{REVIEW_LABEL[state]}</StatusBadge></span>;
}

export function PaymentBadge({ status }: { status: PaymentStatus | null }) {
  const s = status ?? "unknown";
  return <span data-testid="payment-status"><StatusBadge tone={PAYMENT_TONE[s]}>{PAYMENT_LABEL[s]}</StatusBadge></span>;
}

function Ref({ id }: { id: string }) {
  return <span className="t-micro" style={{ color: "var(--text-6)" }}>Result {id}</span>;
}

/** Every figure here is the backend's (the engine's ledger feed) and carries its result reference; nothing on this page adds, compares or rounds an amount. */
export function Overview({ summary }: { summary: SummaryResponse }) {
  return (
    <div className="mt-stack">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MetricCard label="Total expenses" value={money(summary.expenseTotal.paise)} hint={<Ref id={summary.expenseTotal.engineResultRef} />} />
        <MetricCard label="Including items waiting for review" value={money(summary.includingUnresolved.paise)} hint={<Ref id={summary.includingUnresolved.engineResultRef} />} />
        <MetricCard label="Waiting for review" value={money(summary.reviewQueue.amountPaise)} hint={<Ref id={summary.reviewQueue.engineResultRef} />} />
      </div>
      <p className="t-body-sm" style={{ color: "var(--text-6)" }}>
        As of {summary.asOfDate ?? summary.periodEnd}. Only confirmed, not-voided entries count; entries waiting for review are shown separately. Ledger version {summary.watermark}.
      </p>
      <Section title="By cost class" hint="Where the money went. A class with no entries is 'Not entered', which is different from an entered zero.">
        <div className="mt-ledger">
          {summary.byCostClass.map((c) => (
            <div key={c.costClass} className="mt-ledger__row" data-testid={`class-${c.costClass}`}>
              <div className="t-body" style={{ color: "var(--text-3)" }}>{COST_CLASS_LABEL[c.costClass] ?? c.costClass}</div>
              <div className="text-right"><span className="t-metric">{money(c.paise)}</span> <Ref id={c.engineResultRef} /></div>
            </div>
          ))}
          <div data-testid="not-entered">
            {summary.notEntered.map((c) => (
              <div key={c} className="mt-ledger__row">
                <div className="t-body" style={{ color: "var(--text-3)" }}>{COST_CLASS_LABEL[c] ?? c}</div>
                <div className="text-right t-body" style={{ color: "var(--text-5)" }}>Not entered</div>
              </div>
            ))}
          </div>
        </div>
      </Section>
      <Section title="By category">
        {summary.byCategory.length === 0 ? (
          <EmptyState compact title="No entries in this period" description="Add an expense, or choose another period." />
        ) : (
          <div className="mt-ledger">
            {summary.byCategory.map((c) => (
              <div key={c.category} className="mt-ledger__row">
                <div className="t-body" style={{ color: "var(--text-3)" }}>{c.label}</div>
                <div className="text-right"><span className="t-metric">{money(c.paise)}</span> <Ref id={c.engineResultRef} /></div>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Recurring commitments" hint="The part of this period's total that comes from entries marked as recurring.">
        <div className="mt-ledger">
          <div className="mt-ledger__row">
            <div className="t-body" style={{ color: "var(--text-3)" }}>Recurring this period</div>
            <div className="text-right"><span className="t-metric">{money(summary.recurringTotal.paise)}</span> <Ref id={summary.recurringTotal.engineResultRef} /></div>
          </div>
        </div>
      </Section>
    </div>
  );
}

export function ExpenseTable({
  records, filters, meta, onFilters, onCorrect, onRefund, onVoid, onPayment, onAssign,
}: {
  records: ExpenseRecord[];
  filters: ListFilters;
  meta: LedgerMeta;
  onFilters: (f: ListFilters) => void;
  onCorrect: (r: ExpenseRecord) => void;
  onRefund: (r: ExpenseRecord) => void;
  onVoid: (r: ExpenseRecord) => void;
  onPayment: (r: ExpenseRecord, status: PaymentStatus) => void;
  onAssign?: (r: ExpenseRecord) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Category">
          <SelectInput value={filters.category ?? ""} onChange={(v) => onFilters({ ...filters, category: v || undefined })}
            options={[{ value: "", label: "All categories" }, ...meta.categories.map((c) => ({ value: c.id, label: c.label }))]} />
        </Field>
        <Field label="Review state">
          <SelectInput value={filters.reviewState ?? ""} onChange={(v) => onFilters({ ...filters, reviewState: v || undefined })}
            options={[{ value: "", label: "All" }, ...meta.reviewStates.map((s) => ({ value: s, label: REVIEW_LABEL[s] }))]} />
        </Field>
        <Field label="Payment status">
          <SelectInput value={filters.paymentStatus ?? ""} onChange={(v) => onFilters({ ...filters, paymentStatus: v || undefined })}
            options={[{ value: "", label: "All" }, ...meta.paymentStatuses.map((s) => ({ value: s, label: PAYMENT_LABEL[s] }))]} />
        </Field>
        <Field label="From"><TextInput type="date" value={filters.dateFrom ?? ""} onChange={(v) => onFilters({ ...filters, dateFrom: v || undefined })} /></Field>
        <Field label="To"><TextInput type="date" value={filters.dateTo ?? ""} onChange={(v) => onFilters({ ...filters, dateTo: v || undefined })} /></Field>
      </div>
      {records.length === 0 ? (
        <EmptyState title="No expenses match" description="Add an expense, or change the filters." />
      ) : (
        <div className="mt-table-wrap">
          <table className="mt-table">
            <thead>
              <tr><th>Date</th><th>Vendor</th><th>Category</th><th className="text-right">Amount</th><th>Review</th><th>Payment</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={r.id} data-testid="expense-row">
                  <td>{r.effectiveDate}</td>
                  <td>
                    {r.vendor ?? "—"}
                    {r.description && <div className="t-micro" style={{ color: "var(--text-6)" }}>{r.description}</div>}
                    {r.refundOfExpenseId && <div className="t-micro" style={{ color: "var(--text-6)" }}>Refund or credit note</div>}
                    {r.correctsExpenseId && <div className="t-micro" style={{ color: "var(--text-6)" }}>Corrects an earlier entry</div>}
                  </td>
                  <td>{r.categoryLabel}{r.treatment !== "incremental" && <div className="t-micro" style={{ color: "var(--text-6)" }}>{r.treatment.replace(/_/g, " ")}</div>}</td>
                  <td className="text-right">{money(r.amountPaise)}</td>
                  <td><ReviewBadge state={r.reviewState} /></td>
                  <td><PaymentBadge status={r.paymentStatus} /></td>
                  <td>
                    {r.reviewState !== "voided" ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => onCorrect(r)}>Correct</button>
                        <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => onRefund(r)}>Refund</button>
                        <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => onVoid(r)}>Void</button>
                        {onAssign && (r.costClass === "ADVERTISING" || r.costClass === "STORAGE") && (
                          <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2 py-1 t-micro" onClick={() => onAssign(r)}>Split across SKUs</button>
                        )}
                        <select
                          aria-label={`Payment status for ${r.vendor ?? r.categoryLabel}`}
                          value={r.paymentStatus ?? "unknown"}
                          onChange={(e) => onPayment(r, e.target.value as PaymentStatus)}
                          className="mt-input rounded-lg px-2 py-1 t-micro"
                        >
                          {meta.paymentStatuses.map((s) => <option key={s} value={s}>{PAYMENT_LABEL[s]}</option>)}
                        </select>
                      </div>
                    ) : (
                      <span className="t-micro" style={{ color: "var(--text-6)" }}>{r.reviewReason ?? "Voided"}</span>
                    )}
                    <button type="button" className="mt-focus t-micro" style={{ color: "var(--text-5)" }} onClick={() => setOpen(open === r.id ? null : r.id)}>
                      {open === r.id ? "Hide history" : "History"}
                    </button>
                    {open === r.id && <div className="t-micro" style={{ color: "var(--text-6)" }}>Entered {r.createdAt ?? "—"} · {r.origin === "MANUAL" ? "typed in by hand" : "imported"}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function ReviewQueue({ summary, onConfirm, busyId }: { summary: SummaryResponse; onConfirm: (expenseId: string) => void; busyId: string | null }) {
  const items = summary.reviewQueue.items;
  if (items.length === 0) return <EmptyState title="Nothing is waiting for review" description="Entries you leave as 'pending review' appear here until you confirm them." />;
  return (
    <div className="mt-ledger">
      {items.map((i) => (
        <div key={`${i.expenseId}-${i.reason}`} className="mt-ledger__row">
          <div>
            <div className="t-body" style={{ color: "var(--text-3)" }}>{REVIEW_REASON_LABEL[i.reason] ?? i.reason}</div>
            <div className="t-micro" style={{ color: "var(--text-6)" }}>Entry {i.expenseId}</div>
          </div>
          <div className="flex items-center gap-3">
            <span className="t-metric">{money(i.amountPaise)}</span>
            {i.reason === "PENDING_REVIEW" && (
              <button type="button" disabled={busyId === i.expenseId} className="mt-btn mt-focus rounded-lg px-3 py-1 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }} onClick={() => onConfirm(i.expenseId)}>
                Confirm
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
