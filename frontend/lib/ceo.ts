/** Typed client for the CEO conversation API (`backend/src/backend/api/v1/ceo.py`). Every call is a real backend call; nothing in
 * the CEO Hub is mocked or simulated. The UI never computes, derives or re-formats a money figure: numbers reach the screen only
 * inside `TurnResponse.answer` / stored message content, which the backend has already put through its provenance + numeral gate. */

import { apiFetch } from "@/lib/api";

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

export type MessageKind = "TEXT" | "CLARIFICATION" | "ANSWER" | "BRIEFING" | "SYSTEM_NOTE";

export type CeoMessage = {
  id: string;
  role: "USER" | "CEO" | "SYSTEM";
  kind: MessageKind;
  content: string;
  turn_id: string | null;
  created_at: string;
  /** Client-only: a message the seller just sent that the server has not echoed back yet. */
  pending?: boolean;
};

export type CeoRoute = "BUSINESS_STATE" | "ACTION" | "PLAYBOOK" | "ADVISORY" | "SYNTHESIZE" | "CLARIFY" | "OUT_OF_SCOPE";

export type TurnRow = {
  id: string;
  route: CeoRoute;
  route_key: string | null;
  status: string;
  composition_mode: "LLM" | "TEMPLATE" | "TEMPLATE_FALLBACK" | null;
  user_message_id: string;
  ceo_message_id: string | null;
  created_at: string;
};

export type Ref = { kind: string; id: string; source?: string; as_of?: string };

export type FindingStatus = "COMPLETE" | "PARTIAL" | "DENIED" | "FAILED" | "UNAVAILABLE" | "NOT_ENTITLED";

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
  created_at: string;
};

export type InvestigationDetail = {
  investigation: InvestigationMeta;
  agents: Partial<Record<AgentCode, boolean>>;
  messages: CeoMessage[];
  turns: TurnRow[];
  findings: FindingRow[];
};

export type AvailabilityStatus = "PRESENT" | "NOT_PERMITTED" | "NOT_ENTITLED";
export type AgentAvailability = Record<AgentCode, { status: AvailabilityStatus; chatActions: number }>;

export type TurnStatus = "DELIVERED" | "CLARIFIED" | "DENIED" | "FAILED";

export type TurnResponse = {
  turnId: string | null;
  status: TurnStatus;
  route: CeoRoute;
  routeKey: string | null;
  answer: string;
  messageId: string | null;
  compositionMode: string | null;
  clarifyFor: string | null;
  notes: string[];
  findings: FindingRow[];
  timings: Record<string, unknown>;
  events: { kind: string; atMs: number; data: Record<string, unknown> }[];
};

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
    postTurn: (id: string, message: string, period?: ExplicitPeriod | null) =>
      call<TurnResponse>(
        `/investigations/${id}/turns`,
        json("POST", { message, ...(period ? { period_start: period.start, period_end: period.end } : {}) }),
      ),
    resolve: (id: string, note: string) => call<{ status: string }>(`/investigations/${id}/resolve`, json("POST", { resolution_note: note })),
    archive: (id: string) => call<{ status: string }>(`/investigations/${id}/archive`, json("POST", {})),
    setAgentAttached: (id: string, agent: AgentCode, attached: boolean) =>
      call<{ agent: AgentCode; attached: boolean }>(`/investigations/${id}/agents/${agent}`, json("PUT", { attached })),
    getAvailability: () => call<AgentAvailability>("/agents/availability"),
  };
}

export type CeoClient = ReturnType<typeof createCeoClient>;
