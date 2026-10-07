/** Pure view-model logic for the CEO Hub. No React, no fetch, and no arithmetic on any figure: this file only classifies, orders, groups
 * and labels things the backend already decided. Every number a seller sees comes from the backend's gated answer text. */

import type {
  AgentAvailability, AgentCode, CeoMessage, FindingRow, FindingStatus, InvestigationDetail, InvestigationStatus, InvestigationSummary, Ref, TurnRow,
} from "@/lib/ceo";
import { AGENT_CODES } from "@/lib/ceo";

export const AGENT_NAMES: Record<AgentCode, string> = {
  CI: "Competitor Intelligence",
  CFO: "CFO",
  PI: "Product Intelligence",
  CMO: "Slim CMO",
};

// ------------------------------------------------------------------------------------------------ the canvas
/** What a node on the canvas means.
 *  ATTACHED   wired: the CEO may use this agent for new work in THIS investigation
 *  DETACHED   not wired (seller removed it): not used for new work; earlier findings stay visible
 *  LOCKED     the tenant is not entitled to it: cannot be attached, shown with an unlock hint
 *  NO_ACCESS  this member lacks the permission: shown, never presented as usable
 *  UNKNOWN    availability not loaded yet: shown neutral, never as attached */
export type NodeState = "ATTACHED" | "DETACHED" | "LOCKED" | "NO_ACCESS" | "UNKNOWN";

export type CanvasNode = {
  code: AgentCode;
  name: string;
  state: NodeState;
  chatActions: number | null;
  canToggle: boolean; // a wire can be removed (attached) or added (detached AND not locked)
};

export function nodeState(attached: boolean | undefined, availability: AgentAvailability | null, code: AgentCode): NodeState {
  const status = availability?.[code]?.status;
  if (status === "NOT_ENTITLED") return "LOCKED";
  if (attached === true) return status === "NOT_PERMITTED" ? "NO_ACCESS" : "ATTACHED";
  if (status === "NOT_PERMITTED") return "NO_ACCESS";
  if (attached === false) return "DETACHED";
  return "UNKNOWN";
}

export function canvasNodes(
  agents: Partial<Record<AgentCode, boolean>> | null,
  availability: AgentAvailability | null,
  investigationStatus: InvestigationStatus | null,
): CanvasNode[] {
  return AGENT_CODES.map((code) => {
    const state = nodeState(agents?.[code], availability, code);
    const active = investigationStatus === "ACTIVE";
    return {
      code,
      name: AGENT_NAMES[code],
      state,
      chatActions: availability?.[code]?.chatActions ?? null,
      // attached or detached agents can be toggled while the investigation is active; locked / no-access / unknown never can
      canToggle: active && (state === "ATTACHED" || state === "DETACHED"),
    };
  });
}

// ------------------------------------------------------------------------------------------------ findings
const STATUS_VIEW: Record<FindingStatus, { label: string; tone: "accent" | "warning" | "negative" | "info" | "neutral" }> = {
  COMPLETE: { label: "Complete", tone: "accent" },
  PARTIAL: { label: "Partial", tone: "warning" },
  FAILED: { label: "Failed", tone: "negative" },
  DENIED: { label: "Not permitted", tone: "negative" },
  NOT_ENTITLED: { label: "Not on your plan", tone: "warning" },
  UNAVAILABLE: { label: "Unavailable", tone: "neutral" },
};

export function findingStatusView(status: string) {
  return STATUS_VIEW[status as FindingStatus] ?? { label: status, tone: "neutral" as const };
}

/** A finding is a failed/partial LEG when it is anything but complete: shown, never hidden, never blocking the others. */
export const isProblemFinding = (f: FindingRow): boolean => f.status !== "COMPLETE";

const ACTION_LABELS: Record<string, string> = {
  "cfo.financial_health": "Financial health bands",
  "cfo.anomaly_check": "Anomaly check",
  "cfo.strategic_briefing": "CFO briefing",
  "cfo.reconcile": "Marketplace reconciliation",
  "cfo.cash_reconciliation": "Cash reconciliation",
  BS_PNL_LATEST: "Latest profit & loss",
  BS_LEAK_OPEN: "Open leak findings",
  BS_DATA_GAPS: "Inputs still needed",
  BS_HEALTH_BANDS: "Health bands",
  BS_SELLER_CONTEXT: "Your saved goal and notes",
  BS_INGEST_STATUS: "Upload status",
};

export function actionLabel(key: string): string {
  return ACTION_LABELS[key] ?? key.replace(/^[a-z]+\./, "").replace(/^BS_/, "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
}

/** `source` is a specialist code or BUSINESS_STATE (a persisted read by the CEO itself). */
export function sourceLabel(source: string): string {
  return source === "BUSINESS_STATE" ? "CEO · saved results" : (AGENT_NAMES[source as AgentCode] ?? source);
}

/** A finding from an agent that is currently detached is historical evidence: still shown, with its original provenance. */
export function isHistorical(f: FindingRow, agents: Partial<Record<AgentCode, boolean>> | null): boolean {
  return agents != null && agents[f.source as AgentCode] === false;
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

const REF_KINDS: Record<string, string> = {
  ENGINE_RESULT: "Engine result",
  ESTIMATE: "Estimate",
  AGENT_REPORT_FIELD: "Agent report",
  SELLER_PROVIDED: "Seller-provided",
};

export function refLabel(ref: Ref): string {
  return `${REF_KINDS[ref.kind] ?? ref.kind}${ref.source ? ` (${ref.source})` : ""} · ${shortId(ref.id)}`;
}

const byCreated = (a: { created_at: string; id: string }, b: { created_at: string; id: string }) =>
  a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;

/** Merges incoming findings into the known set by id (a finding is append-only on the server, so an existing id is never rewritten),
 * oldest first. Returns the same array instance when nothing is new, so React can skip a re-render. */
export function mergeFindings(existing: FindingRow[], incoming: FindingRow[]): FindingRow[] {
  const known = new Set(existing.map((f) => f.id));
  const fresh = incoming.filter((f) => !known.has(f.id));
  return fresh.length === 0 ? existing : [...existing, ...fresh].sort(byCreated);
}

export type FindingGroup = {
  key: string;
  turnId: string | null;
  question: string | null;
  route: string | null;
  findings: FindingRow[];
};

/** Groups findings under the question that produced them, newest question first (progressive arrival lands at the top). A finding whose
 * turn is not known yet (it arrived by polling before the turn row was read) is grouped under the in-flight question, if any. */
export function groupFindings(findings: FindingRow[], messages: CeoMessage[], turns: TurnRow[], inFlightQuestion: string | null = null): FindingGroup[] {
  const turnById = new Map(turns.map((t) => [t.id, t]));
  const msgById = new Map(messages.map((m) => [m.id, m]));
  const groups = new Map<string, FindingGroup>();
  for (const f of [...findings].sort(byCreated)) {
    const key = f.turn_id ?? "in-flight";
    let g = groups.get(key);
    if (!g) {
      const turn = f.turn_id ? turnById.get(f.turn_id) : undefined;
      g = {
        key,
        turnId: f.turn_id ?? null,
        question: turn ? (msgById.get(turn.user_message_id)?.content ?? null) : inFlightQuestion,
        route: turn?.route ?? null,
        findings: [],
      };
      groups.set(key, g);
    }
    g.findings.push(f);
  }
  return [...groups.values()].reverse();
}

// ------------------------------------------------------------------------------------------------ conversation
export type MessageView = { tone: "user" | "ceo" | "clarify" | "note"; badge: string | null; footnote: string | null };

/** How a message should look. Pure labelling of what the backend already decided (kind, route, composition mode). */
export function messageView(message: CeoMessage, turnById: Map<string, TurnRow>): MessageView {
  if (message.kind === "SYSTEM_NOTE" || message.role === "SYSTEM") return { tone: "note", badge: null, footnote: null };
  if (message.role === "USER") return { tone: "user", badge: null, footnote: null };
  const turn = message.turn_id ? turnById.get(message.turn_id) : undefined;
  if (message.kind === "CLARIFICATION") return { tone: "clarify", badge: "Needs your input", footnote: null };
  if (turn?.route === "OUT_OF_SCOPE") return { tone: "ceo", badge: "Out of scope", footnote: null };
  if (turn?.status === "DENIED") return { tone: "ceo", badge: "Not permitted", footnote: null };
  if (turn?.status === "FAILED") return { tone: "ceo", badge: "Could not complete", footnote: null };
  return {
    tone: "ceo",
    badge: null,
    footnote:
      turn?.composition_mode === "TEMPLATE_FALLBACK"
        ? "Shown from verified data only: the written summary did not pass the safety check."
        : turn?.composition_mode === "TEMPLATE"
          ? "Read directly from your saved, verified results."
          : null,
  };
}

// ------------------------------------------------------------------------------------------------ hub state
export type HubState = "NO_SELECTION" | "LOADING" | "NOT_FOUND" | "ERROR" | "NEW" | "ACTIVE" | "PROCESSING" | "RESOLVED" | "ARCHIVED";

export function hubStateOf(opts: {
  selectedId: string | null;
  status: "idle" | "loading" | "ready" | "error" | "notfound";
  detail: InvestigationDetail | null;
  processing: boolean;
}): HubState {
  if (!opts.selectedId) return "NO_SELECTION";
  if (opts.status === "loading" && !opts.detail) return "LOADING";
  if (opts.status === "notfound") return "NOT_FOUND";
  if (opts.status === "error" && !opts.detail) return "ERROR";
  const d = opts.detail;
  if (!d) return "LOADING";
  if (d.investigation.status === "ARCHIVED") return "ARCHIVED";
  if (d.investigation.status === "RESOLVED") return "RESOLVED";
  if (opts.processing) return "PROCESSING";
  return d.messages.some((m) => m.role === "USER") ? "ACTIVE" : "NEW";
}

export function investigationTitle(i: Pick<InvestigationSummary, "title" | "created_at">): string {
  return i.title?.trim() || `Investigation · ${i.created_at.slice(0, 10)}`;
}

/** Archived investigations are hidden from the default list; everything else is shown, most recently active first (the server's order). */
export function visibleInvestigations(items: InvestigationSummary[], showArchived: boolean): InvestigationSummary[] {
  return showArchived ? items : items.filter((i) => i.status !== "ARCHIVED");
}

/** Appends the seller's just-sent message locally (flagged `pending`) so it shows immediately; the authoritative copy replaces it on refresh. */
export function withPendingMessage(messages: CeoMessage[], text: string, now: string): CeoMessage[] {
  return [...messages, { id: `pending-${now}`, role: "USER", kind: "TEXT", content: text, turn_id: null, created_at: now, pending: true }];
}

/** Light client-side guard for the date pickers. The backend re-validates with the deterministic resolver; this only avoids a round trip. */
export function validatePeriod(start: string, end: string, todayIso: string): string | null {
  if (!start && !end) return null;
  if (!start || !end) return "Choose both a start and an end date, or clear the period.";
  if (start > end) return "The end date is before the start date.";
  if (start > todayIso) return "That period has not started yet.";
  return null;
}

// ------------------------------------------------------------------------------------------------ errors
const ERROR_TEXT: Record<string, string> = {
  CEO_NOT_CONFIGURED: "The CEO is not configured yet. An administrator needs to set it up.",
  INVESTIGATION_NOT_ACTIVE: "This investigation is closed. Re-open it to continue.",
  AGENT_NOT_ENTITLED: "That agent is not on your plan, so it cannot be attached.",
  INVALID_PERIOD: "That date range is not valid. Choose a range that has started.",
  INVALID_MESSAGE: "Write a question between 1 and 4000 characters.",
  NOT_FOUND: "That investigation was not found.",
  FORBIDDEN: "You do not have access to do that.",
  ALREADY_ARCHIVED: "This investigation is already archived.",
  CANNOT_RESOLVE: "Only an active investigation can be resolved.",
  NOT_RESOLVED: "Only a resolved investigation can be reopened.",
};

/** Plain words for an API failure. `detail` is whatever the backend returned (a string, or `{code}`); nothing internal is ever shown. */
export function describeError(status: number | null, detail: unknown): string {
  const code = typeof detail === "object" && detail !== null && "code" in detail ? String((detail as { code: unknown }).code) : null;
  if (code && ERROR_TEXT[code]) return ERROR_TEXT[code];
  if (status === 401) return "Your session has expired. Sign in again.";
  if (status === 403) return ERROR_TEXT.FORBIDDEN;
  if (status === 404) return ERROR_TEXT.NOT_FOUND;
  if (status === 422) return "That request was not valid.";
  if (status === 503) return "The CEO is temporarily unavailable.";
  return "Could not reach the backend.";
}
