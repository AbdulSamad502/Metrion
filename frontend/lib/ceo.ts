/** Typed client for the CEO conversation API (`backend/src/backend/api/v1/ceo.py`). Every call is a real backend call; nothing in
 * the CEO Hub is mocked or simulated. The UI never computes, derives or re-formats a money figure: numbers reach the screen only
 * inside `TurnResponse.answer` / stored message content, which the backend has already put through its provenance + numeral gate. */

import { API_BASE, ApiError, apiFetch, apiFetchForm } from "@/lib/api";

export type GetToken = () => Promise<string | null>;

export type AgentCode = "CI" | "CFO" | "PI" | "CMO";
export const AGENT_CODES: AgentCode[] = ["CI", "CFO", "PI", "CMO"];

export type InvestigationStatus = "ACTIVE" | "RESOLVED" | "ARCHIVED";

export type InvestigationSummary = {
  id: string;
  title: string | null;
  status: InvestigationStatus;
  origin: string;
  created_at: string;
  last_message_at: string;
};

export type InvestigationMeta = InvestigationSummary & {
  resolution_note: string | null;
  resolved_at: string | null;
  summary: string | null;
};

export type MessageKind = "TEXT" | "CLARIFICATION" | "ANSWER" | "BRIEFING" | "SYSTEM_NOTE" | "PLAN";

/** One real choice on a decision card. Built by the backend from the seller's own data; `reason` is the stated rule behind the recommendation. */
export type ClarificationOption = { key: string; label: string; kind: "RECOMMENDED" | "ALTERNATIVE" | "OTHER" | "CANCEL" | "BACK"; reason: string; /** set by the backend on an option that records "unknown" on purpose: offered as Skip */ skip?: boolean; /** set on a FORM card option: opens that playbook's run-form instead of answering */ form?: string };
/** A decision card (spec 6.32): the recommended option first, up to two alternatives, then "Other". Never padded with invented options. */
export type ClarificationCard = { version: number; kind: string; slot: string; options: ClarificationOption[] };
/** The seller answering a card: the card's message id and the chosen option key (null = the free-text "Other", sent as the message text). */
export type ClarificationReply = { id: string; option: string | null };

export type CeoMessage = {
  id: string;
  role: "USER" | "CEO" | "SYSTEM";
  kind: MessageKind;
  content: string;
  turn_id: string | null;
  created_at: string;
  /** Only a CEO CLARIFICATION message that has real candidates to offer. */
  choices?: ClarificationCard | null;
  /** Client-only: a message the seller just sent that the server has not echoed back yet. */
  pending?: boolean;
  /** The send failed and the thread could not be refreshed, so the server's copy is unknown: shown as not sent, never as still sending. */
  failed?: boolean;
};

export type CeoRoute = "BUSINESS_STATE" | "ACTION" | "PLAYBOOK" | "ADVISORY" | "SYNTHESIZE" | "CLARIFY" | "OUT_OF_SCOPE";

export type TurnRow = {
  id: string;
  route: CeoRoute;
  route_key: string | null;
  status: string;
  composition_mode: "LLM" | "TEMPLATE" | "TEMPLATE_FALLBACK" | null;
  /** UI_ACTION: the seller chose a quick action (no classifier ran); CLASSIFIER: the model routed a typed message. */
  route_source?: "CLASSIFIER" | "UI_ACTION";
  /** How the execution ended, stored once with the turn: SUCCEEDED | PARTIAL | FAILED | PENDING_INPUT | DECLINED. Absent for turns from before the accounting cut-over. A DELIVERED turn can still be FAILED: a delivered answer alone is not a successful execution. */
  outcome?: TurnOutcome | null;
  /** The stored routing record (`investigation_turn.classifier_result`, returned with the turn rows). Only `approvalRequiredFor` is read: the action key a turn was refused for because it needs a stored approval plan, which does not exist yet. */
  classifier_result?: { approvalRequiredFor?: string | null } | null;
  user_message_id: string;
  ceo_message_id: string | null;
  created_at: string;
};

export type Ref = { kind: string; id: string; source?: string; as_of?: string };

export type FindingStatus = "COMPLETE" | "PARTIAL" | "DENIED" | "FAILED" | "UNAVAILABLE" | "NOT_ENTITLED";

/** The display snapshot stored with a finding (spec R7 as amended). Every `value` is the backend's own formatting of a figure it resolved
 * through `ref` for this tenant: the UI shows it verbatim and never computes, rounds or re-formats it. */
/** One remembered item (spec agent-memory.md), as the seller gave it. `shared` items are visible to every agent; the rest belong to one agent. */
export type MemoryItem = { id: string; label: string; value: string; shared: boolean; agent: string; basis: string; createdAt: string };

/** One thing an agent reported (spec agent-needs-and-shared-knowledge.md 6.3, GET /ceo/findings). `trustLabel` is the fixed wording the backend chose for the trust level
 * ("You said", "Calculated by the engine", "Reported by <agent>, not verified"); figures are references only: a value is never shown here. */
export type SharedFinding = {
  id: string; agent: string; kind: string; subject: string | null; text: string; trust: "SELLER_STATED" | "ENGINE_VERIFIED" | "AGENT_REPORTED"; trustLabel: string;
  figureRefs: { kind: string; id: string; label?: string; resolvable: boolean }[]; sourceRef: { kind: string; id?: string } | null; createdAt: string;
};
export type SharedFindingsList = { items: SharedFinding[]; hidden: { agent: string; count: number; message: string }[]; hiddenTotal: number };

export type PresentationFigure = { label: string; value: string; register: string; as_of: string | null; note: string | null; ref: Ref };
export type PresentationFact = { label: string; text: string; basis: string };
/** Two stored values for one quantity that disagree. `text` is the block the backend rendered from both verified values; neither is chosen or averaged. */
export type PresentationConflict = { what: string; text: string; kind: string; refIds: string[] };
export type Presentation = {
  version: number;
  headline: string;
  figures: PresentationFigure[];
  /** absent on snapshots written before conflicts existed */
  conflicts?: PresentationConflict[];
  facts: PresentationFact[];
  gaps: string[];
  offers: { key: string; label: string }[];
  /** Content a specialist WROTE (titles, hashtags...). Shown quoted and labelled, never as a figure. Absent on snapshots written before it existed. */
  artefacts?: { title: string; items: string[]; note: string | null }[];
};

export type FindingRow = {
  id: string;
  turn_id?: string;
  source: string; // CFO | PI | CI | CMO | GST_LOOKUP | BUSINESS_STATE
  action_key: string;
  status: FindingStatus;
  figure_refs: Ref[];
  report_ref: Record<string, string> | null;
  gap_reason: string | null;
  agent_run_id: string | null;
  /** null / absent for findings written before the snapshot existed: the card then shows its references only. */
  presentation?: Presentation | null;
  created_at: string;
};

/** A health-strip entry: a persisted Business State read, presented the same way as a finding. */
export type HealthEntry = {
  key: string;
  status: string;
  period: string | null;
  asOf: string | null;
  previewHint: string | null;
  presentation: Presentation | null;
};

/** "Show flow": how one turn was answered, from the audit rows only. */
export type FlowRun = {
  id: string;
  agentId: string | null;
  triggerRef: string | null;
  status: string;
  permissionCheck: string | null;
  entitlementCheck: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  reason: string | null;
};
export type TurnFlow = {
  turnId: string;
  route: CeoRoute;
  routeKey: string | null;
  routeSource: "CLASSIFIER" | "UI_ACTION";
  status: string;
  compositionMode: string | null;
  timings: Record<string, unknown> | null;
  ceo: FlowRun | null;
  legs: FlowRun[];
};

/** A quick action the seller chose with a deterministic control. It skips the classifier and nothing else. */
/** What the backend says about one stored attachment: its type is decided from the content, and `status` says whether its text could be read. */
/** What the backend says about a CSV / XLSX it could read as a table: the sheets and their sizes (never cell values). `UNREADABLE` carries a plain reason. */
export type UploadedTable = { status: "READ"; sheets: { name: string; rows: number; columns: number; headerRow: number | null; truncated: boolean }[]; sheetsTruncated: boolean } | { status: "UNREADABLE"; note: string };
export type UploadedAttachment = { id: string; filename: string; type: string; byteSize: number; status: "OK" | "NOT_READ" | "FAILED"; note: string | null; table?: UploadedTable | null; duplicate?: boolean };

export type UiActionKind = "BUSINESS_STATE" | "ACTION" | "PLAYBOOK" | "SYNTHESIZE";
/** A decision playbook's structured form inputs (spec 6.33): money is integer paise and every cost carries an explicit state. Built by a form, never by a model. */
export type CostValue = { state: "AMOUNT"; amount_paise: number } | { state: "NONE_CONFIRMED" } | { state: "UNKNOWN"; reason?: string | null };
export type UiAction = { kind: UiActionKind; key?: string; slots?: Record<string, string>; inputs?: Record<string, unknown> };

export type PriceImpactFormSupport = {
  competitors: { id: string; label: string }[];
  feeOptions: { marketplace: string; category: string; feeType: string }[];
  storedCost: { amountPaise: number | null; formatted: string | null; effectiveFrom: string | null; reason: string | null } | null;
  maxCandidatePrices: number | null;
};
export type StoredInputRow = { id: string; createdAt: string; value: Record<string, unknown>; reason: string | null; /** the stored value, formatted by the backend */ summary: string };
export type NewProductFormSupport = { quotes: StoredInputRow[]; budget: StoredInputRow[]; budgetTargetRef: string };
/** One seller input saved through the existing CFO expense path (needs the CFO key and financials.adjust). */
export type SaveInputBody = { target_type: "SKU" | "ACCOUNT"; target_ref: string; field: "cogs_per_unit" | "supplier.quote" | "batch.budget"; value: Record<string, unknown>; supersedes_id?: string | null };

export type PlanStatus = "AWAITING_APPROVAL" | "APPROVED" | "DECLINED" | "EXPIRED" | "SUPERSEDED" | string;
/** A stored approval plan (ceo-approval-workflow.md). The PLAN message of the thread is rendered from THIS row (matched by `plannedTurnId`), never parsed from text.
 * `planHash` is what the Approve button sends back with the plan id: the server recomputes it and refuses a mismatch. */
export type PlanView = {
  id: string;
  status: PlanStatus;
  planHash: string;
  plan: { summary_text?: string; title?: string; compact_lines?: string[]; details?: string[]; legs?: { action_key: string; meters?: { meter_code: string; units: number }[] }[]; [k: string]: unknown };
  createdAt: string;
  expiresAt: string;
  plannedTurnId: string | null;
  executionTurnId: string | null;
  viewerIsRequester: boolean;
  decisionReason?: string | null;
};

export type InvestigationDetail = {
  plans?: PlanView[];
  investigation: InvestigationMeta;
  agents: Partial<Record<AgentCode, boolean>>;
  messages: CeoMessage[];
  turns: TurnRow[];
  findings: FindingRow[];
};

export type NeedStatus = "FULFILLED" | "REUSED" | "DENIED" | "NOT_ATTACHED" | "NOT_ENTITLED" | "UNAVAILABLE" | "FAILED" | "TIMED_OUT" | "CONFIG_MISSING" | "OFFERED" | "DROPPED";
/** One follow-up lookup the CEO made for a specialist (a `ceo_need` row). It holds no money and no text: who asked whom, for what, and how it ended. */
export type NeedRow = { id: string; needKey: string; requesterAgent: string; providerKey: string; status: NeedStatus | string; createdAt: string; turnMessageId: string | null };

export type AvailabilityStatus = "PRESENT" | "NOT_PERMITTED" | "NOT_ENTITLED";
export type AgentAvailability = Record<AgentCode, { status: AvailabilityStatus; chatActions: number }>;

export type TurnOutcome = "SUCCEEDED" | "PARTIAL" | "FAILED" | "PENDING_INPUT" | "DECLINED";

export type TurnStatus = "DELIVERED" | "CLARIFIED" | "DENIED" | "FAILED" | "PLANNED"; // PLANNED is vocabulary only: nothing produces it until the approval workflow exists

export type TurnResponse = {
  turnId: string | null;
  status: TurnStatus;
  route: CeoRoute;
  routeKey: string | null;
  routeSource?: "CLASSIFIER" | "UI_ACTION";
  answer: string;
  messageId: string | null;
  compositionMode: string | null;
  clarifyFor: string | null;
  choices?: ClarificationCard | null;
  clarificationId?: string | null;
  notes: string[];
  findings: FindingRow[];
  timings: Record<string, unknown>;
  events: { kind: string; atMs: number; data: Record<string, unknown> }[];
  /** True when this is the STORED outcome of an earlier submission with the same clientRequestId: nothing new was written or run. */
  replayed?: boolean;
};

/** One progress event of a running turn (labels only: never a figure or the answer; the backend's whitelist guarantees it). */
export type TurnEvent = { kind: string; atMs: number; data: Record<string, unknown> };

/** An explicit, seller-chosen date range (ISO dates). The backend validates it with the same deterministic resolver it uses for
 * every period; the model can neither choose nor withhold it. */
export type ExplicitPeriod = { start: string; end: string };

const BASE = "/api/v1/ceo";

export function createCeoClient(getToken: GetToken) {
  const call = async <T>(path: string, init?: RequestInit): Promise<T> => apiFetch<T>(`${BASE}${path}`, await getToken(), init);
  const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
  return {
    listInvestigations: () => call<InvestigationSummary[]>("/investigations"),
    createInvestigation: (title?: string) => call<{ investigationId: string }>("/investigations", json("POST", { title: title ?? null })),
    getInvestigation: (id: string) => call<InvestigationDetail>(`/investigations/${id}`),
    getFindings: (id: string, turnId?: string) =>
      call<FindingRow[]>(`/investigations/${id}/findings${turnId ? `?turn_id=${encodeURIComponent(turnId)}` : ""}`),
    getNeeds: (id: string) => call<{ items: NeedRow[] }>(`/investigations/${id}/needs`),
    uploadAttachment: async (id: string, file: File) => {
      const form = new FormData();
      form.append("file", file);
      return apiFetchForm<UploadedAttachment>(`${BASE}/investigations/${id}/attachments`, await getToken(), form);
    },
    postTurn: (id: string, message: string, period?: ExplicitPeriod | null, action?: UiAction | null, clarification?: ClarificationReply | null, attachmentIds?: string[], clientRequestId?: string | null) =>
      call<TurnResponse>(
        `/investigations/${id}/turns`,
        json("POST", {
          message,
          ...(period ? { period_start: period.start, period_end: period.end } : {}),
          ...(action ? { action: { kind: action.kind, key: action.key ?? null, slots: action.slots ?? {}, ...(action.inputs ? { inputs: action.inputs } : {}) } } : {}),
          ...(clarification ? { clarification: { id: clarification.id, option: clarification.option } } : {}),
          ...(attachmentIds && attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
          ...(clientRequestId ? { clientRequestId } : {}), // one logical submission = one id: the server answers a retry with the stored outcome instead of running it again
        }),
      ),
    /** The ONLY way a plan is approved: the plan id and the plan hash the seller was shown. Typing "yes" in the chat never reaches this. */
    approvePlan: (id: string, planId: string, planHash: string) => call<{ status: string; replayed?: boolean }>(`/investigations/${id}/plans/${planId}/approve`, json("POST", { plan_hash: planHash })),
    declinePlan: (id: string, planId: string, reason?: string | null) => call<{ status: string }>(`/investigations/${id}/plans/${planId}/decline`, json("POST", { reason: reason ?? null })),
    getHealth: () => call<{ entries: HealthEntry[] }>("/state/health"),
    getMemory: () => call<{ items: MemoryItem[] }>("/memory"),
    forgetMemory: (id: string) => call<{ forgotten: string }>(`/memory/${encodeURIComponent(id)}/forget`, json("POST", {})),
    getSharedFindings: () => call<SharedFindingsList>("/findings"),
    forgetSharedFinding: (id: string) => call<{ forgotten: string }>(`/findings/${encodeURIComponent(id)}/forget`, json("POST", {})),
    getPriceImpactForm: (sku?: string) => call<PriceImpactFormSupport>(`/forms/price-impact${sku ? `?sku=${encodeURIComponent(sku)}` : ""}`),
    getNewProductForm: (sku?: string) => call<NewProductFormSupport>(`/forms/new-product${sku ? `?sku=${encodeURIComponent(sku)}` : ""}`),
    saveInput: async (body: SaveInputBody) => apiFetch<{ manualAdjustmentId?: string }>("/api/v1/cfo/expenses", await getToken(), { method: "PUT", body: JSON.stringify(body) }),
    getFlow: (id: string, turnId: string) => call<TurnFlow>(`/investigations/${id}/turns/${turnId}/flow`),
    resolve: (id: string, note: string) => call<{ status: string }>(`/investigations/${id}/resolve`, json("POST", { resolution_note: note })),
    reopen: (id: string) => call<{ status: string }>(`/investigations/${id}/reopen`, json("POST", {})),
    archive: (id: string) => call<{ status: string }>(`/investigations/${id}/archive`, json("POST", {})),
    setAgentAttached: (id: string, agent: AgentCode, attached: boolean) =>
      call<{ agent: AgentCode; attached: boolean }>(`/investigations/${id}/agents/${agent}`, json("PUT", { attached })),
    getAvailability: () => call<AgentAvailability>("/agents/availability"),
    /** Server-sent progress of the next/current turn in this investigation. Resolves when the stream ends (the turn finished, the server closed it,
     * or `signal` aborted); rejects if it cannot be opened. It is an ACCELERATOR only: the findings poll keeps running, so a stream that never
     * delivers anything (another API worker ran the turn, a proxy buffers) costs the seller nothing. */
    streamEvents: async (id: string, onEvent: (e: TurnEvent) => void, signal?: AbortSignal): Promise<void> => {
      const token = await getToken();
      const res = await fetch(`${API_BASE}${BASE}/investigations/${id}/events`, {
        signal, headers: { Accept: "text/event-stream", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (!res.ok || !res.body) throw new ApiError(res.status, res.statusText);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        for (let end = buffer.indexOf("\n\n"); end >= 0; end = buffer.indexOf("\n\n")) {
          const frame = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue; // a comment / keep-alive frame
          try {
            onEvent(JSON.parse(line.slice(6)) as TurnEvent);
          } catch {
            /* a malformed frame is skipped; the poll covers whatever it carried */
          }
        }
      }
    },
  };
}

export type CeoClient = ReturnType<typeof createCeoClient>;
