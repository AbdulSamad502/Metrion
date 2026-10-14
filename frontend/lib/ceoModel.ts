/** Pure view-model logic for the CEO Hub. No React, no fetch, and no arithmetic on any figure: this file only classifies, orders, groups
 * and labels things the backend already decided. Every number a seller sees comes from the backend's gated answer text. */

import type {
  AgentAvailability, AgentCode, CeoMessage, ExplicitPeriod, FindingRow, FindingStatus, FlowRun, InvestigationDetail, InvestigationStatus, InvestigationSummary,
  NeedRow, Ref, TurnFlow, TurnRow, UiAction,
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
  /** What this node shows as its result: the newest COMPLETE finding that has something to show, never a newer partial / failed / refused one. */
  result: NodeResult;
  chatActions: number | null;
  canToggle: boolean; // a wire can be removed (attached) or added (detached AND not locked)
};

export function nodeState(attached: boolean | undefined, availability: AgentAvailability | null, code: AgentCode): NodeState {
  // Attached only says what the conversation intends. Whether the agent is actually usable (plan, permission) is known only once availability has
  // loaded: until then (or if it could not load) nothing may be shown as connected.
  if (availability === null) return "UNKNOWN";
  const status = availability?.[code]?.status;
  if (status === "NOT_ENTITLED") return "LOCKED";
  if (attached === true) return status === "NOT_PERMITTED" ? "NO_ACCESS" : "ATTACHED";
  if (status === "NOT_PERMITTED") return "NO_ACCESS";
  if (attached === false) return "DETACHED";
  return "UNKNOWN";
}

export type NodeResult = {
  /** the newest complete, usable finding's own snapshot headline (null when there is none) */
  headline: string | null;
  headlineAt: string | null;
  /** the newest finding of this agent of ANY status, shown separately and only when it is not the one the headline came from */
  newer: { status: FindingStatus; at: string; label: string } | null;
  /** this agent has produced findings, but none is complete and usable: say so instead of showing an incomplete result as a result */
  noCompleteResult: boolean;
};

/** A finding is a usable result when it completed AND its snapshot holds a figure, a fact or written content (a gap sentence alone is not a result). */
const isUsableResult = (f: FindingRow): boolean =>
  f.status === "COMPLETE" && !!f.presentation && (f.presentation.figures.length > 0 || f.presentation.facts.length > 0 || (f.presentation.artefacts?.length ?? 0) > 0) && !!f.presentation.headline;

/** Selection only, nothing combined, counted or derived: the newest complete usable finding supplies the headline; the newest finding of any
 * status is reported beside it (status, time, which check) so the seller sees that a newer check happened and how it ended. Timestamps,
 * statuses and the finding's own provenance are untouched. */
export function nodeResult(findings: FindingRow[], code: AgentCode): NodeResult {
  let usable: FindingRow | null = null;
  let newest: FindingRow | null = null;
  for (const f of findings) {
    if (f.source !== code) continue;
    if (!newest || byCreated(newest, f) < 0) newest = f;
    if (isUsableResult(f) && (!usable || byCreated(usable, f) < 0)) usable = f;
  }
  return {
    headline: usable?.presentation?.headline ?? null,
    headlineAt: usable?.created_at ?? null,
    newer: newest && newest.id !== usable?.id ? { status: newest.status, at: newest.created_at, label: actionLabel(newest.action_key) } : null,
    noCompleteResult: newest !== null && usable === null,
  };
}

export function canvasNodes(
  agents: Partial<Record<AgentCode, boolean>> | null,
  availability: AgentAvailability | null,
  investigationStatus: InvestigationStatus | null,
  findings: FindingRow[] = [],
): CanvasNode[] {
  return AGENT_CODES.map((code) => {
    const state = nodeState(agents?.[code], availability, code);
    const active = investigationStatus === "ACTIVE";
    return {
      code,
      name: AGENT_NAMES[code],
      state,
      result: nodeResult(findings, code),
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
  gst_lookup: "GST rate lookup",
  "cfo.gst_lookup": "GST rate lookup",
  "service.gst_lookup": "GST rate lookup",
  "ci.request_price_scenario": "Competitor price comparison",
  "pi.report": "Product research report",
  BS_COMPETITOR_SNAPSHOT: "Competitor prices",
  BS_PI_REPORT_LATEST: "Product research status",
  BS_CMO_WORKFLOW: "Listing content status",
  BS_PNL_LATEST: "Latest profit & loss",
  BS_LEAK_OPEN: "Open leak findings",
  BS_DATA_GAPS: "Inputs still needed",
  BS_HEALTH_BANDS: "Health bands",
  BS_SELLER_CONTEXT: "Your saved goal and notes",
  BS_INGEST_STATUS: "Upload status",
  // The CEO's own saved-results questions (the business-state catalog): plain words, never the key ("Qt leaks").
  QT_AGENT_FINDINGS: "What the specialists found",
  QT_COMPETITORS_PRICES: "Competitor prices",
  QT_DATA_GAPS: "Inputs still needed",
  QT_GOALS: "Your saved goal and notes",
  QT_LEAKS: "Where money is leaking",
  QT_LISTING_CONTENT: "Listing content written",
  QT_NOT_STORED: "Not stored yet",
  QT_PRODUCT_IDEAS: "Product ideas found",
  QT_PROFIT_BY_PERIOD: "Profit by period",
  QT_SELLER_FACTS: "What you told me",
};

export function actionLabel(key: string): string {
  return ACTION_LABELS[key] ?? key.replace(/^[a-z]+\./, "").replace(/^BS_/, "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
}

/** `source` is a specialist code or BUSINESS_STATE (a persisted read by the CEO itself). */
export function sourceLabel(source: string): string {
  if (source === "GST_LOOKUP") return "GST lookup";
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

// ------------------------------------------------------------------------------------------------ presentation
/** Where a finding's full analysis lives (spec 6.35 workspace link): the owning agent's own page, deep-linked to the exact stored record when the finding points at one
 * (a research run for Product Intelligence). Only pages that exist are ever linked; a finding that was refused or has no page returns null. */
export function findingLink(f: Pick<FindingRow, "source" | "action_key" | "status" | "report_ref">): { href: string; label: string } | null {
  if (f.status === "DENIED" || f.status === "FAILED" || f.status === "UNAVAILABLE") return null;
  const run = f.report_ref?.runId;
  // ONE "View Detailed Research" button per research answer, on the saved-report finding only. The run and supplier-lookup findings of the same turn carry no link of their own
  // (they used to add a second, generic button).
  if (f.source === "PI") return f.action_key === "pi.report" ? { href: run ? `/dashboard/pi?run=${encodeURIComponent(run)}` : "/dashboard/pi", label: "View Detailed Research" } : null;
  if (f.source === "CFO") return { href: "/dashboard/cfo", label: "Open the full finance analysis" };
  if (f.source === "CI") return { href: "/dashboard/competitors", label: "Open the competitor details" };
  if (f.source === "CMO") return { href: "/dashboard/cmo", label: "Open the written content" };
  return null;
}

/** The five registers a figure can carry (cfo-agent.md 7.4.7). The chip says how much to trust the number and where it came from. */
const REGISTER_VIEW: Record<string, { label: string; tone: "accent" | "info" | "warning" | "neutral" }> = {
  VERIFIED: { label: "Verified", tone: "accent" },
  DERIVED: { label: "Derived from verified", tone: "info" },
  MANUAL: { label: "Seller-provided", tone: "neutral" },
  ESTIMATE: { label: "Estimate", tone: "warning" },
  UNAVAILABLE: { label: "Unavailable", tone: "neutral" },
};

export function registerView(register: string) {
  return REGISTER_VIEW[register] ?? { label: register, tone: "neutral" as const };
}

/** "as of 2026-09-30": the backend's ISO date shown as given. */
export const asOfLabel = (asOf: string | null): string | null => (asOf ? `as of ${asOf.slice(0, 10)}` : null);

/** Does this finding have anything beyond references to show? */
export function hasPresentation(f: FindingRow): boolean {
  const p = f.presentation;
  return !!p && (p.figures.length > 0 || p.facts.length > 0 || p.gaps.length > 0 || p.offers.length > 0 || (p.conflicts?.length ?? 0) > 0 || (p.artefacts?.length ?? 0) > 0);
}

// ------------------------------------------------------------------------------------------------ quick actions
/** A deterministic control that asks for one catalog item directly. It skips the classifier (the slow, uncertain step) and nothing else:
 * the backend applies the same attachment, permission, entitlement and slot checks as for a typed question, and says plainly when it refuses. */
export type QuickAction = {
  id: string;
  label: string;
  action: UiAction;
  /** needs the seller's explicit date range (never guessed) */
  needsPeriod: boolean;
  /** the agent that must be wired in for this to run */
  needsAgent: AgentCode | null;
};

export const QUICK_ACTIONS: QuickAction[] = [
  { id: "pnl", label: "Latest profit & loss", action: { kind: "BUSINESS_STATE", key: "BS_PNL_LATEST" }, needsPeriod: false, needsAgent: "CFO" },
  { id: "bands", label: "Health bands", action: { kind: "BUSINESS_STATE", key: "BS_HEALTH_BANDS" }, needsPeriod: false, needsAgent: "CFO" },
  { id: "leaks", label: "Open leaks", action: { kind: "BUSINESS_STATE", key: "BS_LEAK_OPEN" }, needsPeriod: false, needsAgent: "CFO" },
  { id: "gaps", label: "Inputs still needed", action: { kind: "BUSINESS_STATE", key: "BS_DATA_GAPS" }, needsPeriod: false, needsAgent: "CFO" },
  { id: "competitors", label: "Competitor prices", action: { kind: "BUSINESS_STATE", key: "BS_COMPETITOR_SNAPSHOT" }, needsPeriod: false, needsAgent: "CI" },
  { id: "research", label: "Product research status", action: { kind: "BUSINESS_STATE", key: "BS_PI_REPORT_LATEST" }, needsPeriod: false, needsAgent: "PI" },
  { id: "report", label: "Latest research report", action: { kind: "ACTION", key: "pi.report" }, needsPeriod: false, needsAgent: "PI" },
  { id: "listing", label: "Listing content status", action: { kind: "BUSINESS_STATE", key: "BS_CMO_WORKFLOW" }, needsPeriod: false, needsAgent: "CMO" },
  { id: "briefing", label: "Business briefing", action: { kind: "PLAYBOOK", key: "BUSINESS_BRIEFING" }, needsPeriod: false, needsAgent: null },
  { id: "diagnosis", label: "Why did profit drop?", action: { kind: "PLAYBOOK", key: "PROFIT_DIAGNOSIS" }, needsPeriod: true, needsAgent: "CFO" },
  { id: "anomaly", label: "Anomaly check", action: { kind: "ACTION", key: "cfo.anomaly_check" }, needsPeriod: true, needsAgent: "CFO" },
];

/** Whether a chip can be used right now, and if not, the plain reason. Advisory only: the backend re-checks everything. */
export function quickActionState(
  qa: QuickAction,
  agents: Partial<Record<AgentCode, boolean>> | null,
  period: ExplicitPeriod | null,
): { enabled: boolean; reason: string | null } {
  if (qa.needsAgent && agents?.[qa.needsAgent] !== true) return { enabled: false, reason: `${AGENT_NAMES[qa.needsAgent]} is not attached to this investigation.` };
  if (qa.needsPeriod && !period) return { enabled: false, reason: "Choose a period first: the CEO never guesses dates." };
  return { enabled: true, reason: null };
}

// ------------------------------------------------------------------------------------------------ live progress
const STAGE_TEXT: Record<string, string> = {
  TURN_RECEIVED: "Reading your question…",
  TURN_ADMITTED: "Reading your question…",
  CLASSIFIED: "Choosing what to check…",
  PLAN_VALIDATED: "Checking your access and plan…",
  LEG_STARTED: "Asking the specialists…",
  LEG_FINISHED: "A specialist has answered…",
  STATE_READ: "Reading your saved results…",
  SYNTHESIS_STARTED: "Writing the answer…",
  ANSWER_READY: "Checking the answer against your data…",
};

/** Plain words for a live progress event, or null for one that adds nothing (including a kind this version does not know). */
export const stageLabel = (kind: string): string | null => STAGE_TEXT[kind] ?? null;

// ------------------------------------------------------------------------------------------------ flow
const ROUTE_LABELS: Record<string, string> = {
  BUSINESS_STATE: "Read saved results",
  ACTION: "Ran one specialist action",
  PLAYBOOK: "Ran a playbook",
  ADVISORY: "Advice from saved results",
  SYNTHESIZE: "Summarised the investigation",
  CLARIFY: "Asked for clarification",
  OUT_OF_SCOPE: "Out of scope",
};

export const routeLabel = (route: string): string => ROUTE_LABELS[route] ?? route;

export const routeSourceLabel = (source: string): string =>
  source === "UI_ACTION" ? "You chose a quick action, so no model decided the route." : "A model classified your message into this route.";

const RUN_STATUS: Record<string, string> = {
  QUEUED: "Queued", COMPLETE: "Completed", PARTIAL: "Partial", DENIED: "Not permitted", FAILED: "Failed", RUNNING: "Running", NOT_ENTITLED: "Not on your plan",
};
export const runStatusLabel = (status: string): string => RUN_STATUS[status] ?? status;

export type FlowStep = { key: string; title: string; detail: string | null; status: string };

const stageDuration = (s: unknown): number | null => {
  if (typeof s !== "object" || s === null) return null;
  const { startMs, endMs } = s as { startMs?: unknown; endMs?: unknown };
  // a duration in milliseconds, not a money figure
  return typeof startMs === "number" && typeof endMs === "number" ? endMs - startMs : null;
};

/** The steps of a turn for the "Show flow" view: the CEO anchor first, then each specialist leg, with timings the backend recorded. */
export function flowSteps(flow: TurnFlow): FlowStep[] {
  const steps: FlowStep[] = [];
  const stages = (flow.timings?.stages ?? {}) as Record<string, unknown>;
  const timed = (name: string): string | null => {
    const d = stageDuration(stages[name]);
    return d === null ? null : `${d} ms`;
  };
  const runStep = (r: FlowRun, title: string, detail: string | null): FlowStep => ({ key: r.id, title, detail, status: runStatusLabel(r.status) });
  if (flow.ceo) steps.push(runStep(flow.ceo, "CEO", [routeLabel(flow.route), timed("classification") ?? timed("route_resolution")].filter(Boolean).join(" · ") || null));
  for (const leg of flow.legs) {
    const checks = [leg.permissionCheck && `permission: ${leg.permissionCheck}`, leg.entitlementCheck && `plan: ${leg.entitlementCheck}`].filter(Boolean).join(" · ");
    steps.push(runStep(leg, leg.triggerRef ? actionLabel(leg.triggerRef) : (leg.agentId ?? "Specialist"), [checks, leg.reason].filter(Boolean).join(" · ") || null));
  }
  return steps;
}

// ------------------------------------------------------------------------------------------------ conversation
export type MessageView = { tone: "user" | "ceo" | "clarify" | "note"; badge: string | null; footnote: string | null };

/** How a message should look. Pure labelling of what the backend already decided (kind, route, composition mode). */
/** True only for a turn the backend refused because the action needs a stored approval plan (a supported field written with the turn), never inferred from text or status alone. */
export const approvalRefused = (turn: TurnRow | null | undefined): boolean => turn?.status === "DENIED" && !!turn.classifier_result?.approvalRequiredFor;

export function messageView(message: CeoMessage, turnById: Map<string, TurnRow>): MessageView {
  if (message.kind === "SYSTEM_NOTE" || message.role === "SYSTEM") return { tone: "note", badge: null, footnote: null };
  if (message.role === "USER") return { tone: "user", badge: null, footnote: null };
  const turn = message.turn_id ? turnById.get(message.turn_id) : undefined;
  if (message.kind === "PLAN") return { tone: "ceo", badge: "Plan to approve", footnote: null };
  if (message.kind === "CLARIFICATION") return { tone: "clarify", badge: "Needs your input", footnote: null };
  if (turn?.route === "OUT_OF_SCOPE") return { tone: "ceo", badge: "Out of scope", footnote: null };
  if (approvalRefused(turn)) return { tone: "ceo", badge: "Needs an approved plan", footnote: "Approval of a stored plan is not available yet, so nothing was run." };
  if (turn?.status === "DENIED") return { tone: "ceo", badge: "Not permitted", footnote: null };
  if (turn?.status === "FAILED") return { tone: "ceo", badge: "Could not complete", footnote: null };
  // A delivered answer is not proof of a successful execution: the stored outcome says whether a required step failed or is still waiting for the seller.
  if (turn?.outcome === "FAILED") return { tone: "ceo", badge: "Could not complete", footnote: null };
  if (turn?.outcome === "PENDING_INPUT") return { tone: "ceo", badge: "Waiting for your input", footnote: null };
  if (turn?.outcome === "PARTIAL") return { tone: "ceo", badge: "Partly completed", footnote: null };
  return {
    tone: "ceo",
    badge: null,
    footnote:
      turn?.composition_mode === "TEMPLATE_FALLBACK"
        ? "Shown from verified data only: the written summary did not pass the safety check."
        : turn?.composition_mode === "TEMPLATE" && !/^(cmo|pi)\./.test(turn.route_key ?? "")
          ? "Read directly from your saved, verified results." // not for written content or web findings: those say what they are in the answer itself
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

/** One logical submission's identifier. A retry of the SAME submission reuses it; a new submission (even with identical text) gets a new one. */
let submissionCounter = 0;
export function newSubmissionId(): string {
  const c = typeof globalThis !== "undefined" ? (globalThis as { crypto?: { randomUUID?: () => string; getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto : undefined;
  if (c?.randomUUID) return c.randomUUID();
  let hex: string;
  if (c?.getRandomValues) {
    hex = Array.from(c.getRandomValues(new Uint8Array(16)), (x) => x.toString(16).padStart(2, "0")).join("");
  } else {
    // No platform randomness at all (not a browser Metrion supports): still unique within this page, which is all an idempotency id needs.
    submissionCounter += 1;
    hex = (Date.now().toString(16) + submissionCounter.toString(16).padStart(8, "0")).padStart(32, "0").slice(-32);
  }
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20)}`; // a version-4 shaped UUID, the shape the API validates
}

/** What makes two sends the same submission: everything the server would act on. Used only to decide whether a send that just FAILED is being retried unchanged. */
export function submissionFingerprint(investigationId: string, text: string, period: unknown, action: unknown, clarification: unknown, attachmentIds: string[]): string {
  return JSON.stringify([investigationId, text, period ?? null, action ?? null, clarification ?? null, attachmentIds]);
}

/** The server holds a seller question that has no CEO answer yet (the page was refreshed or reopened while a turn was running, or the reply was lost). Derived only from the stored thread:
 * nothing is assumed about WHY it has no answer, so the screen says "still being answered", never "failed" and never "done". */
export function isAwaitingAnswer(messages: CeoMessage[] | undefined, investigationStatus: string | undefined): boolean {
  if (investigationStatus !== "ACTIVE" || !messages || messages.length === 0) return false;
  const last = messages[messages.length - 1];
  return last.role === "USER" && !last.pending && !last.failed;
}

export const RECEIVED_BUT_NO_REPLY =
  "Your question reached the server, but its reply did not come back. Check the conversation above before asking again: sending it again would ask it twice.";

/** After a send whose reply was lost: does the server's own thread already hold this question as a NEW seller message? (There were `userBefore` seller messages before the send.)
 * Only the client's own just-attempted submission is matched, by its text and by the count growing: this never decides that two separate submissions are one. */
export function serverAlreadyHasSubmission(messages: CeoMessage[], text: string, userBefore: number): boolean {
  const user = messages.filter((m) => m.role === "USER" && !m.pending && !m.failed);
  return user.length > userBefore && user[user.length - 1].content.startsWith(text);
}

/** A send that failed leaves its local copy flagged `failed` (not `pending`): when the refresh that would replace it also fails, the question must not read "Sending…" forever. */
export function markPendingFailed(messages: CeoMessage[]): CeoMessage[] {
  return messages.map((m) => (m.pending ? { ...m, pending: false, failed: true } : m));
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
  TURN_IN_PROGRESS: "The CEO is still answering your previous question. Try again in a moment.",
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

// ------------------------------------------------------------------------------------------------ follow-up lookups (needs)
/** Fixed labels for what the CEO looked up on a specialist's behalf. An unknown key is shown as its own key, never guessed at. */
const NEED_THING: Record<string, string> = { GST_RATE_FOR_PRODUCT: "the GST rate", LANDED_COST_FOR_IDEA: "the landed cost", MARGIN_AT_PRICE: "the margin at that price", CEO_READ: "a saved result" };
const PROVIDER_NAME: Record<string, string> = { "cfo.gst_lookup": "the CFO's GST lookup", "service.gst_lookup": "the GST lookup" };
const REQUESTER_NAME: Record<string, string> = { CEO: "The CEO", CMO: "The Slim CMO", PI: "Product Intelligence", CI: "Competitor Intelligence", CFO: "The CFO" };
type NeedTone = "positive" | "neutral" | "warning";
const NEED_OUTCOME: Record<string, { text: string; tone: NeedTone }> = {
  FULFILLED: { text: "Done: the result is in the findings.", tone: "positive" },
  REUSED: { text: "Looked up earlier in this conversation.", tone: "positive" },
  DENIED: { text: "Not available to you.", tone: "warning" },
  NOT_ATTACHED: { text: "That agent is turned off for this conversation.", tone: "warning" },
  NOT_ENTITLED: { text: "Your plan does not include it.", tone: "warning" },
  UNAVAILABLE: { text: "Not available right now.", tone: "warning" },
  FAILED: { text: "It could not be completed.", tone: "warning" },
  TIMED_OUT: { text: "It took too long, so nothing was filled in.", tone: "warning" },
  CONFIG_MISSING: { text: "Not configured yet by your operator.", tone: "warning" },
  OFFERED: { text: "Offered to you; it runs only if you accept.", tone: "neutral" },
  DROPPED: { text: "Left out of this answer.", tone: "neutral" },
};

export type NeedStepView = { id: string; text: string; outcome: string; tone: NeedTone; requester: string; provider: string };

export function needStepView(n: NeedRow): NeedStepView {
  const requester = REQUESTER_NAME[n.requesterAgent] ?? n.requesterAgent;
  const provider = PROVIDER_NAME[n.providerKey] ?? n.providerKey;
  const thing = NEED_THING[n.needKey] ?? n.needKey;
  const o = NEED_OUTCOME[n.status] ?? { text: n.status, tone: "neutral" as NeedTone };
  return { id: n.id, text: `${requester} asked ${provider} for ${thing}.`, outcome: o.text, tone: o.tone, requester, provider };
}

/** Needs placed with the message (turn) that produced them; the rest (no matching message) are returned separately, in the order received. */
export function needsByMessage(needs: NeedRow[], messages: CeoMessage[]): { byMessage: Map<string, NeedRow[]>; unplaced: NeedRow[] } {
  const ids = new Set(messages.map((m) => m.id));
  const byMessage = new Map<string, NeedRow[]>();
  const unplaced: NeedRow[] = [];
  for (const n of needs) {
    if (n.turnMessageId && ids.has(n.turnMessageId)) byMessage.set(n.turnMessageId, [...(byMessage.get(n.turnMessageId) ?? []), n]);
    else unplaced.push(n);
  }
  return { byMessage, unplaced };
}
