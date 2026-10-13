"use client";

import { useState } from "react";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import type { PlanView } from "@/lib/ceo";

const STATE: Record<string, { tone: Tone; label: string; note: string }> = {
  AWAITING_APPROVAL: { tone: "warning", label: "Waiting for your approval", note: "" },
  APPROVED: { tone: "accent", label: "Approved", note: "" },
  DECLINED: { tone: "neutral", label: "Declined", note: "Declined: nothing was run, sent or used up." },
  EXPIRED: { tone: "neutral", label: "Expired", note: "This plan expired. Nothing was run, sent or used up. Ask again for a new plan." },
  SUPERSEDED: { tone: "neutral", label: "Replaced", note: "A newer plan replaced this one. Nothing was run, sent or used up." },
};

const timeOf = (iso: string): string => {
  const d = new Date(iso);
  return d.toString() === "Invalid Date" ? "" : d.toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

/** The plan the CEO prepared, rendered from the STORED plan row (never parsed from the chat text). The card is COMPACT: a few short lines (what runs, the confirmed inputs, the model, the cost,
 * the validity) and the buttons; the full detail (every frozen input, the hash, the disclosure wording) is behind "Details" and is the same complete text the server stores and hashes. Once the
 * plan is decided the card shrinks to its title: the approval or decline is one short line in the conversation, and the plan is never repeated there.
 * Approve and Decline are shown ONLY while the plan is waiting AND the viewer is the person who asked. Approve sends the plan id and the plan hash shown here; the server
 * recomputes the hash and refuses a mismatch. Typing "yes" in the chat bar never approves anything. */
export function PlanCard({
  plan, busy, closed, onApprove, onDecline,
}: {
  plan: PlanView | null;
  busy: string | null;
  closed: boolean;
  onApprove?: (planId: string, planHash: string) => void;
  onDecline?: (planId: string) => void;
}) {
  if (!plan) {
    return (
      <div data-testid="plan-card" data-status="UNKNOWN" className="mt-2 rounded-xl px-4 py-3 t-body-sm" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-4)" }}>
        This plan could not be loaded. Nothing was run.
      </div>
    );
  }
  const state = STATE[plan.status] ?? { tone: "neutral" as Tone, label: plan.status, note: "" };
  const [showDetails, setShowDetails] = useState(false);
  const full = String(plan.plan.summary_text ?? "").split("\n").filter((l) => l.trim());
  const compact = Array.isArray(plan.plan.compact_lines) ? plan.plan.compact_lines.map(String).filter((l) => l.trim()) : [];
  const short = compact.length > 0 ? compact : full.slice(0, 3); // an older plan without compact lines: its first lines
  const title = typeof plan.plan.title === "string" && plan.plan.title.trim() ? plan.plan.title : short[0] ?? "Plan";
  const open = plan.status === "AWAITING_APPROVAL";
  const canDecide = open && plan.viewerIsRequester && !closed && !!onApprove && !!onDecline;
  const working = busy === plan.id;
  const button = "mt-btn mt-focus min-h-[40px] rounded-lg px-4 py-1.5 t-body-sm font-bold sm:min-h-0";
  return (
    <section
      aria-label="Plan to approve" data-testid="plan-card" data-status={plan.status}
      className="mt-2 flex flex-col gap-2.5 rounded-xl px-4 py-3" style={{ border: "1px solid var(--accent-border-default)", background: "var(--bg-card)" }}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="t-meta font-bold" style={{ color: "var(--accent)" }}>Plan</span>
        <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
        {open && compact.length === 0 && <span className="t-meta" style={{ color: "var(--text-6)" }} data-testid="plan-expiry">Valid until {timeOf(plan.expiresAt)}</span>}
      </div>
      {open ? (
        <ul className="m-0 flex list-none flex-col gap-1 p-0 t-body-sm" style={{ color: "var(--text-2)" }} data-testid="plan-lines">
          {short.map((l, i) => (
            <li key={i} className="whitespace-pre-wrap break-words">{l}</li>
          ))}
        </ul>
      ) : (
        <div className="t-body-sm break-words" style={{ color: "var(--text-3)" }} data-testid="plan-title">{title}</div>
      )}
      {state.note && <div className="t-body-sm" style={{ color: "var(--text-4)" }}>{state.note}</div>}
      {open && !plan.viewerIsRequester && (
        <div className="t-body-sm" style={{ color: "var(--text-4)" }} data-testid="plan-not-requester">Only the person who asked can approve or decline this plan.</div>
      )}
      {canDecide && (
        <div className="flex flex-wrap items-center gap-2" data-testid="plan-actions">
          <button type="button" disabled={!!busy} onClick={() => onApprove?.(plan.id, plan.planHash)} className={button} style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 }}>
            {working ? "Working…" : "Approve"}
          </button>
          <button type="button" disabled={!!busy} onClick={() => onDecline?.(plan.id)} className={button} style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)", opacity: busy ? 0.6 : 1 }}>
            Decline
          </button>
        </div>
      )}
      <div>
        <button type="button" aria-expanded={showDetails} onClick={() => setShowDetails((v) => !v)} data-testid="plan-details-toggle" className="mt-focus t-meta font-bold" style={{ color: "var(--accent)" }}>
          {showDetails ? "Hide details" : "Details"}
        </button>
      </div>
      {showDetails && (
        <div className="flex flex-col gap-1 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="plan-details">
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {full.map((l, i) => (
              <li key={i} className="whitespace-pre-wrap break-words">{l}</li>
            ))}
          </ul>
          <div className="t-meta break-all" style={{ color: "var(--text-6)" }} data-testid="plan-hash-full">Plan hash: {plan.planHash}</div>
        </div>
      )}
      <div className="t-meta" style={{ color: "var(--text-6)" }} data-testid="plan-hash">Plan {plan.planHash.slice(0, 8)}</div>
    </section>
  );
}
