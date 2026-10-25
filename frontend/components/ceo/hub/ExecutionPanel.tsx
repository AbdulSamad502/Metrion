"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import type { AgentCode, TurnRow } from "@/lib/ceo";
import { actionLabel, approvalRefused, type HubState } from "@/lib/ceoModel";
import type { TurnProgress } from "@/lib/useCeoHub";

/** What the current task is doing, shown only from state the backend already reports. Nothing here is simulated:
 *   - the live stage text and the specialists running right now come from the turn's event stream (`turn.stage`, `turn.working`);
 *   - the finished turns, their outcome and the time they were recorded come from the investigation's own turn rows;
 *   - "awaiting your input" is a CEO clarification the backend asked and nobody has answered yet.
 * There is deliberately no "Planning" or "Awaiting approval" state: the backend has no such turn state yet. They are added here only when
 * it reports them (docs/design/ui-ux-phase2-notes.md), never inferred from the UI. */
export type ExecutionStatus = "APPROVAL_REQUIRED" | "IDLE" | "AWAITING_INPUT" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED" | "DENIED" | "CLOSED";

const STATUS_VIEW: Record<ExecutionStatus, { label: string; tone: "neutral" | "accent" | "warning" | "negative" | "info" }> = {
  APPROVAL_REQUIRED: { label: "Needs an approved plan", tone: "warning" },
  IDLE: { label: "Idle", tone: "neutral" },
  AWAITING_INPUT: { label: "Awaiting your input", tone: "warning" },
  RUNNING: { label: "Running", tone: "accent" },
  COMPLETED: { label: "Completed", tone: "accent" },
  PARTIAL: { label: "Partly completed", tone: "warning" },
  FAILED: { label: "Failed", tone: "negative" },
  DENIED: { label: "Not allowed", tone: "negative" },
  CLOSED: { label: "Conversation closed", tone: "neutral" },
};

const OUTCOME_VIEW: Record<string, { label: string; tone: "neutral" | "accent" | "warning" | "negative" }> = {
  SUCCEEDED: { label: "Completed", tone: "accent" },
  PARTIAL: { label: "Partly completed", tone: "warning" },
  FAILED: { label: "Could not complete", tone: "negative" },
  PENDING_INPUT: { label: "Waiting for your input", tone: "warning" },
  DECLINED: { label: "Explained", tone: "neutral" },
};

const TURN_STATUS_VIEW: Record<string, { label: string; tone: "neutral" | "accent" | "warning" | "negative" }> = {
  DELIVERED: { label: "Completed", tone: "accent" },
  CLARIFIED: { label: "Asked you a question", tone: "warning" },
  DENIED: { label: "Not allowed", tone: "negative" },
  FAILED: { label: "Failed", tone: "negative" },
  PLANNED: { label: "Planned", tone: "neutral" }, // vocabulary only for now; never shown as a failure
  // A turn that has not finished (the backend's in-flight statuses). Shown as in progress, not as the raw code ("plan validated"); never as done or failed.
  RECEIVED: { label: "In progress", tone: "accent" },
  CAP_CHECKED: { label: "In progress", tone: "accent" },
  CLASSIFIED: { label: "In progress", tone: "accent" },
  PLAN_VALIDATED: { label: "In progress", tone: "accent" },
  DISPATCHED: { label: "In progress", tone: "accent" },
  GATHERED: { label: "In progress", tone: "accent" },
  COMPOSED: { label: "In progress", tone: "accent" },
};

/** The one status of the task right now, from the hub's own state and the newest turn. Pure: no clock, no arithmetic. */
export function executionStatusOf(opts: { state: HubState; needsInput: boolean; lastTurnStatus: string | null; error: string | null; lastTurnOutcome?: string | null; lastTurnApprovalRefused?: boolean; awaitingAnswer?: boolean }): ExecutionStatus {
  if (opts.state === "PROCESSING" || (opts.awaitingAnswer && opts.state !== "RESOLVED" && opts.state !== "ARCHIVED")) return "RUNNING";
  if (opts.state === "RESOLVED" || opts.state === "ARCHIVED") return "CLOSED";
  if (opts.needsInput || opts.lastTurnOutcome === "PENDING_INPUT") return "AWAITING_INPUT";
  if (opts.lastTurnOutcome === "FAILED") return "FAILED"; // delivered, but a required step did not succeed
  if (opts.error || opts.lastTurnStatus === "FAILED") return "FAILED";
  if (opts.lastTurnStatus === "DENIED") return opts.lastTurnApprovalRefused ? "APPROVAL_REQUIRED" : "DENIED";
  if (opts.lastTurnStatus === "DELIVERED" && opts.lastTurnOutcome === "PARTIAL") return "PARTIAL"; // some steps finished and some did not: never headlined as plain "Completed"
  if (opts.lastTurnStatus === "DELIVERED") return "COMPLETED";
  return "IDLE";
}

/** What a turn with no catalog key was: plain words, never the raw route code. */
const ROUTE_WORDS: Record<string, string> = {
  ADVISORY: "General question", CLARIFY: "Question for you", OUT_OF_SCOPE: "Outside what Metrion does", BUSINESS_STATE: "Saved results", ACTION: "Specialist request",
  PLAYBOOK: "Guided analysis", SYNTHESIZE: "Summary of findings",
};

const stamp = (iso: string): string => {
  const d = new Date(iso);
  return d.toString() === "Invalid Date" ? iso : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
};

export function ExecutionPanel({
  state, needsInput, turn, turns, working, awaitingAnswer = false,
}: {
  state: HubState;
  needsInput: boolean;
  turn: TurnProgress;
  turns: TurnRow[];
  /** the specialists running right now, with plain-words labels (already built by the hub from the live event stream) */
  working: { code: AgentCode; label: string }[];
  /** the server holds a question with no answer yet (refresh mid-run): "still being answered", derived from the stored thread */
  awaitingAnswer?: boolean;
}) {
  const newest = turns.length ? turns[turns.length - 1] : null;
  const status = executionStatusOf({ state, needsInput, lastTurnStatus: newest?.status ?? null, error: turn.error, lastTurnOutcome: newest?.outcome ?? null, lastTurnApprovalRefused: approvalRefused(newest), awaitingAnswer });
  const view = STATUS_VIEW[status];
  const recent = turns.slice(-5).reverse();
  return (
    <section aria-label="Task status" data-testid="execution-panel" data-status={status} className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="mt-eyebrow">Task status</h2>
        <StatusBadge tone={view.tone} dot>{view.label}</StatusBadge>
      </div>

      {status === "RUNNING" && (
        <div className="rounded-xl px-3 py-2.5" style={{ border: "1px solid var(--border-subtle)" }} data-testid="execution-running">
          <p className="m-0 t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>
            {turn.stage ?? (awaitingAnswer ? "Your last question is still being answered. This page checks again every few seconds." : "Working…")}
          </p>
          {turn.question && (
            <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-5)" }}>
              For: “{turn.question.slice(0, 120)}”
            </p>
          )}
          {working.length > 0 && (
            <ul className="m-0 mt-2 flex list-none flex-col gap-1 p-0" aria-label="Agents working now">
              {working.map((w) => (
                <li key={w.code} className="flex items-center gap-2 t-meta" style={{ color: "var(--text-3)" }}>
                  <span className="mt-spinner inline-block h-3 w-3" aria-hidden />
                  <span className="font-semibold">{w.code}</span> {w.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {status === "AWAITING_INPUT" && (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-4)" }}>
          The CEO asked a question and is waiting for your answer. Nothing has run for it yet.
        </p>
      )}
      {status === "APPROVAL_REQUIRED" && (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-4)" }}>
          That action needs an approved plan before it can run, and approval is not available yet. Nothing was run, sent or charged.
        </p>
      )}
      {status === "PARTIAL" && (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-4)" }} data-testid="execution-partial">
          Some steps finished and some did not. What finished is saved in the findings below; the conversation says what is missing.
        </p>
      )}
      {status === "FAILED" && (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-4)" }}>
          The last request did not complete. The conversation explains why in plain words, and you can ask again.
        </p>
      )}

      {recent.length === 0 ? (
        <p className="m-0 t-meta" style={{ color: "var(--text-5)" }} data-testid="execution-empty">
          No task has run in this conversation yet. When you ask something, each step appears here as it happens.
        </p>
      ) : (
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Recent tasks" data-testid="execution-history">
          {recent.map((t) => {
            const tv = (approvalRefused(t) ? { label: "Needs an approved plan", tone: "warning" as const } : undefined) ?? (t.status === "DELIVERED" && t.outcome ? OUTCOME_VIEW[t.outcome] : undefined) ?? TURN_STATUS_VIEW[t.status] ?? { label: t.status.toLowerCase().replace(/_/g, " "), tone: "neutral" as const };
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-2 rounded-lg px-2.5 py-1.5" style={{ border: "1px solid var(--border-subtle)" }}>
                <span className="min-w-0 flex-1 truncate t-body-sm" style={{ color: "var(--text-2)" }}>
                  {t.route_key ? actionLabel(t.route_key) : (ROUTE_WORDS[t.route] ?? t.route.toLowerCase().replace(/_/g, " "))}
                </span>
                <StatusBadge tone={tv.tone}>{tv.label}</StatusBadge>
                <time className="t-meta" dateTime={t.created_at} style={{ color: "var(--text-5)" }}>{stamp(t.created_at)}</time>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
