"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { ExpenseTrackerSection } from "@/components/cfo/sections/ExpenseTrackerSection";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import type { Period } from "@/lib/cfoV2/dashboard";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";

type LedgerEntry = {
  id: string;
  entryDate: string;
  amountDisplay: string;
  category: string;
  vendor: string | null;
  description: string | null;
  gstAmountDisplay: string | null;
  gstTreatmentUnconfirmed: boolean;
  allocatedComponent: string | null;
  hold: string;
  confirmedClass: string | null;
  suggestedClass: string | null;
  suggestionReason: string | null;
};

const CLASS_LABEL: Record<string, string> = {
  OVERHEAD: "Overhead (reduces Operating Profit)",
  ALLOCATED_COST: "Allocated cost (already inside Contribution Profit)",
  OWNER_DRAWING: "Owner drawing (not a business expense)",
  INVENTORY_PURCHASE: "Inventory purchase",
  CAPITAL: "Capital item",
  TAX_ASSET: "Tax asset",
  MARKETPLACE_DEDUCTION: "Marketplace deduction",
};
const HOLD_TEXT: Record<string, string> = {
  POSSIBLE_DUPLICATE: "On hold: looks like a duplicate of another entry, so it is not counted.",
  MAY_OVERLAP_UNCONFIRMED: "On hold: marketplaces often deduct this themselves, so it is not counted until you say it is not already in a settlement.",
};
const COMPONENTS = ["ADVERTISING", "PACKAGING", "STORAGE", "LOGISTICS", "OTHER"] as const;

/** Expenses: the existing Expense Tracker, plus the expense ledger — entries, the class Metrion suggests (a suggestion until you confirm it), held entries, and GST shown beside
 * the amount with its treatment marked as not confirmed. */
export function ExpensesTab({ period, getToken }: { period: Period; getToken: () => Promise<string | null> }) {
  const { getToken: clerkToken } = useAuth();
  const canAdjust = useCanAdjust();
  const entries = useCfoData<{ entries: LedgerEntry[] }>("/ledger/entries", `period_start=${period.start}&period_end=${period.end}`);
  const [component, setComponent] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const post = async (path: string, body?: object) => {
    setError(null);
    try {
      await apiFetch(`/api/v1/cfo${path}`, await clerkToken(), { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
      entries.reload();
    } catch (e) {
      setError(friendlyApiError(e, "That could not be saved"));
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="Expense ledger" className="flex flex-col gap-3">
        <h3 className="t-label">Expense ledger</h3>
        {error && <ErrorNotice message={error} />}
        <SectionState state={entries} title="expenses">
          {(d) =>
            d.entries.length === 0 ? (
              <p className="t-body">No expenses recorded for this period. Upload an expense file under Data &amp; imports.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {d.entries.map((e) => (
                  <li key={e.id} className="flex flex-col gap-1 rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
                    <div className="t-body">
                      {e.entryDate} · {e.category} · {e.amountDisplay}
                      {e.vendor ? ` · ${e.vendor}` : ""}
                    </div>
                    {e.gstAmountDisplay && (
                      <div className="t-meta" style={{ color: "var(--text-5)" }}>
                        GST in this amount: {e.gstAmountDisplay}
                        {e.gstTreatmentUnconfirmed ? " — GST treatment not confirmed; the amount is used as entered." : ""}
                      </div>
                    )}
                    {e.hold !== "NONE" && (
                      <div role="status" className="t-meta">
                        {HOLD_TEXT[e.hold] ?? "On hold, not counted."}
                        {canAdjust && (
                          <button type="button" className="ml-2 underline" onClick={() => post(`/ledger/entries/${e.id}/release`)}>
                            It is a genuine, separate expense
                          </button>
                        )}
                      </div>
                    )}
                    {e.confirmedClass ? (
                      <div className="t-meta">Class: {CLASS_LABEL[e.confirmedClass] ?? e.confirmedClass}{e.allocatedComponent ? ` · ${e.allocatedComponent.toLowerCase()}` : ""}</div>
                    ) : e.suggestedClass ? (
                      <div className="flex flex-wrap items-center gap-2 t-meta">
                        <span>
                          Suggested: {CLASS_LABEL[e.suggestedClass] ?? e.suggestedClass} — not counted until you confirm{e.suggestionReason ? ` (${e.suggestionReason})` : ""}.
                        </span>
                        {canAdjust && e.suggestedClass === "ALLOCATED_COST" && (
                          <select aria-label="Which cost" value={component[e.id] ?? ""} onChange={(ev) => setComponent((c) => ({ ...c, [e.id]: ev.target.value }))}>
                            <option value="">Which cost?</option>
                            {COMPONENTS.map((c) => (
                              <option key={c} value={c}>
                                {c.toLowerCase()}
                              </option>
                            ))}
                          </select>
                        )}
                        {canAdjust && (
                          <button
                            type="button"
                            disabled={e.suggestedClass === "ALLOCATED_COST" && !component[e.id]}
                            onClick={() => post("/ledger/classes", { class: e.suggestedClass, entry_id: e.id, ...(component[e.id] ? { allocated_component: component[e.id] } : {}) })}
                          >
                            Confirm
                          </button>
                        )}
                      </div>
                    ) : (
                      <div className="t-meta">No class yet — not counted in Operating Profit.</div>
                    )}
                  </li>
                ))}
              </ul>
            )
          }
        </SectionState>
      </section>
      <ExpenseTrackerSection getToken={getToken} />
    </div>
  );
}
