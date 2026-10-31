/** An in-memory stand-in for the CEO API, honouring the same CONTRACT the real backend tests pin (tenant 404s, closed investigations,
 * entitlement refusal on attach, SYSTEM_NOTEs, append-only findings). It exists so UI behaviour can be tested deterministically; it does
 * no orchestration of its own: tests script what the "server" persisted and when, exactly as the real turn endpoint would. */

import { createImagesApi } from "@/lib/cmoImages";
import { createPerformanceApi } from "@/lib/cmoPerformance";
import { ApiError } from "@/lib/api";
import type { HistoryCompare, HistoryList, HistoryRecommendations, HistoryVersionDetail, MemoryItem, NeedRow, SharedFinding, SharedFindingsList } from "@/lib/ceo";
import type {
  AgentAvailability, AgentCode, CeoClient, UploadedAttachment, UploadedTable, NewProductFormSupport, PriceImpactFormSupport, SaveInputBody, CeoMessage, CeoRoute, ClarificationCard, ClarificationReply, ExplicitPeriod, FindingRow, HealthEntry, InvestigationDetail, InvestigationStatus,
  InvestigationSummary, TurnEvent, TurnFlow, TurnResponse, TurnRow, UiAction,
} from "@/lib/ceo";
import type { FeedFactory, FeedOptions, FindingsFeed } from "@/lib/ceoPolling";

type Stored = InvestigationDetail & { tenant: string };

export const ALL_PRESENT: AgentAvailability = {
  CI: { status: "PRESENT", chatActions: 1 },
  CFO: { status: "PRESENT", chatActions: 6 },
  PI: { status: "PRESENT", chatActions: 1 },
  CMO: { status: "PRESENT", chatActions: 0 },
};

let counter = 0;
const uid = (p: string) => `${p}-${(++counter).toString().padStart(8, "0")}-0000-0000-0000-000000000000`;
const ts = () => new Date(Date.UTC(2026, 9, 8, 9, 0, counter)).toISOString();

export function finding(over: Partial<FindingRow> & Pick<FindingRow, "source" | "action_key" | "status">): FindingRow {
  return { id: uid("f"), turn_id: undefined, figure_refs: [], report_ref: null, gap_reason: null, agent_run_id: null, created_at: ts(), ...over };
}

export type TurnScript = {
  status?: TurnResponse["status"];
  route?: CeoRoute;
  answer: string;
  kind?: CeoMessage["kind"];
  compositionMode?: TurnRow["composition_mode"];
  findings?: FindingRow[];
  /** a decision card on the CEO message (kind CLARIFICATION) */
  choices?: ClarificationCard;
};

export class FakeCeo {
  tenant = "A";
  availability: AgentAvailability = structuredClone(ALL_PRESENT);
  store = new Map<string, Stored>();
  calls: { method: string; args: unknown[] }[] = [];
  failNextTurn: ApiError | null = null;
  requestIds: (string | null)[] = []; // the clientRequestId of every postTurn, in order (kept apart from `calls`, whose argument shapes other tests pin)
  health: HealthEntry[] = [];
  healthError: ApiError | null = null;
  memory: MemoryItem[] = [];
  shared: SharedFinding[] = [];
  hiddenFindings: SharedFindingsList["hidden"] = [];
  sharedError: ApiError | null = null;
  needs = new Map<string, NeedRow[]>();
  flows = new Map<string, TurnFlow>();
  /** live-event stream: tests push events; `streamFails` makes it refuse to open (the poll must still do the whole job) */
  streamFails = false;
  priceForm: PriceImpactFormSupport = { competitors: [], feeOptions: [], storedCost: null, maxCandidatePrices: 5 };
  productForm: NewProductFormSupport = { quotes: [], budget: [], budgetTargetRef: "tenant-a" };
  saved: SaveInputBody[] = [];
  uploads: { id: string; name: string }[] = [];
  uploadFails: ApiError | null = null;
  uploadFailsFor: string | null = null; // a file NAME whose upload fails (the others succeed)
  uploadTable: UploadedTable | null = null; // what the backend reports about a spreadsheet it read (or could not read)
  streams: { id: string; emit: (e: TurnEvent) => void; closed: boolean }[] = [];
  private pending: { id: string; message: string; period: ExplicitPeriod | null; action: UiAction | null; clarification: ClarificationReply | null; resolve: (r: TurnResponse) => void; reject: (e: unknown) => void } | null = null;

  seed(over: Partial<Stored> & { id?: string; status?: InvestigationStatus; title?: string | null } = {}): string {
    const id = over.id ?? uid("i");
    const meta = {
      id, title: over.title ?? "Why did profit drop?", status: over.status ?? "ACTIVE", origin: "USER_CHAT", created_at: ts(), last_message_at: ts(),
      resolution_note: null, resolved_at: null, summary: null,
    };
    this.store.set(id, {
      tenant: over.tenant ?? this.tenant,
      investigation: { ...meta, ...(over.investigation ?? {}) },
      agents: over.agents ?? { CI: true, CFO: true, PI: true, CMO: true },
      messages: over.messages ?? [],
      turns: over.turns ?? [],
      findings: over.findings ?? [],
      ...(over.plans ? { plans: over.plans } : {}),
    });
    return id;
  }

  private visible(id: string): Stored {
    const s = this.store.get(id);
    if (!s || s.tenant !== this.tenant) throw new ApiError(404, { code: "NOT_FOUND" }); // another tenant's id is indistinguishable from a missing one
    return s;
  }

  count(method: string): number {
    return this.calls.filter((c) => c.method === method).length;
  }

  /** What the server persists the moment a specialist leg finishes (visible to the polling endpoint immediately). */
  emitFinding(f: FindingRow): FindingRow {
    const p = this.pending;
    if (!p) throw new Error("no turn in flight");
    const s = this.visible(p.id);
    const row = { ...f, turn_id: f.turn_id ?? "turn-in-flight" };
    s.findings.push(row);
    return row;
  }

  /** The turn endpoint finishing: persists the CEO message + turn row, then answers the in-flight POST. */
  completeTurn(script: TurnScript): void {
    const p = this.pending;
    if (!p) throw new Error("no turn in flight");
    this.pending = null;
    const s = this.visible(p.id);
    const turnId = uid("t");
    const userMsg = s.messages.find((m) => m.content === p.message && m.turn_id === null && m.role === "USER");
    const ceoMsg: CeoMessage = { id: uid("m"), role: "CEO", kind: script.kind ?? "ANSWER", content: script.answer, turn_id: turnId, created_at: ts(), ...(script.choices ? { choices: script.choices } : {}) };
    s.messages.push(ceoMsg);
    s.turns.push({
      id: turnId, route: script.route ?? "ADVISORY", route_key: null, status: script.status ?? "DELIVERED", composition_mode: script.compositionMode ?? "LLM",
      user_message_id: userMsg?.id ?? "", ceo_message_id: ceoMsg.id, created_at: ts(),
    });
    for (const f of s.findings) if (f.turn_id === "turn-in-flight") f.turn_id = turnId;
    for (const f of script.findings ?? []) s.findings.push({ ...f, turn_id: turnId });
    if (userMsg) userMsg.turn_id = turnId;
    p.resolve({
      turnId, status: script.status ?? "DELIVERED", route: script.route ?? "ADVISORY", routeKey: null, answer: script.answer, messageId: ceoMsg.id,
      compositionMode: script.compositionMode ?? "LLM", clarifyFor: null, choices: script.choices ?? null, clarificationId: script.choices ? ceoMsg.id : null, notes: [], findings: s.findings.filter((f) => f.turn_id === turnId), timings: {}, events: [],
    });
  }

  failTurn(error: unknown): void {
    const p = this.pending;
    if (!p) throw new Error("no turn in flight");
    this.pending = null;
    p.reject(error);
  }

  /** CMO 3.0 M7: what the listing-history routes return in a test; `error` makes every one of them fail the way the server would. */
  history: { list?: HistoryList; versions?: Record<string, HistoryVersionDetail>; compare?: HistoryCompare; recommendations?: HistoryRecommendations; error?: unknown } = {};

  private failHistory(): never {
    throw this.history.error ?? new ApiError(404, "Not found");
  }

  private historyFor(q: { sku?: string | null; marketplace?: string | null; offset?: number }): HistoryList {
    if (this.history.error || !this.history.list) return this.failHistory();
    const all = this.history.list;
    const versions = all.versions.filter((v) => (!q.sku || v.sku === q.sku) && (!q.marketplace || v.marketplace === q.marketplace));
    return { ...all, filters: { sku: q.sku ?? null, marketplace: q.marketplace ?? null }, versions, total: versions.length, offset: q.offset ?? 0, hasMore: false, empty: versions.length === 0 };
  }

  client(): CeoClient {
    const rec = <T>(method: string, args: unknown[], fn: () => T | Promise<T>): Promise<T> => {
      this.calls.push({ method, args });
      try {
        return Promise.resolve(fn());
      } catch (e) {
        return Promise.reject(e);
      }
    };
    return {
      listInvestigations: () =>
        rec("listInvestigations", [], () =>
          [...this.store.values()].filter((s) => s.tenant === this.tenant).map((s): InvestigationSummary => ({ ...s.investigation })).reverse(),
        ),
      createInvestigation: (title?: string) =>
        rec("createInvestigation", [title], () => {
          const entitled = (c: AgentCode) => this.availability[c].status !== "NOT_ENTITLED";
          const agents: Partial<Record<AgentCode, boolean>> = { CI: entitled("CI"), CFO: entitled("CFO"), PI: entitled("PI"), CMO: entitled("CMO") };
          return { investigationId: this.seed({ title: title ?? null, agents }) };
        }),
      getInvestigation: (id: string) =>
        rec("getInvestigation", [id], () => {
          const { tenant: _t, ...detail } = this.visible(id);
          void _t;
          return structuredClone(detail) as InvestigationDetail;
        }),
      getFindings: (id: string) => rec("getFindings", [id], () => structuredClone(this.visible(id).findings)),
      // The plan endpoints: approving needs the plan id AND the exact hash (a mismatch is refused, as the real server does), and a decided plan is final.
      approvePlan: (id: string, planId: string, planHash: string) =>
        rec("approvePlan", [id, planId, planHash], () => {
          const s = this.visible(id);
          const p = (s.plans ?? []).find((x) => x.id === planId);
          if (!p) throw new ApiError(404, { code: "NOT_FOUND" });
          if (p.planHash !== planHash) throw new ApiError(409, { code: "PLAN_CHANGED", message: "This plan changed, or the approval does not match it. Nothing was run." });
          if (p.status !== "AWAITING_APPROVAL") throw new ApiError(409, { code: "PLAN_NOT_AWAITING", message: "This plan is no longer waiting for approval. Nothing was run." });
          p.status = "APPROVED";
          s.messages.push({ id: uid("m"), role: "CEO", kind: "ANSWER", content: "Here is what Slim CMO wrote for the plan you approved.", turn_id: null, created_at: ts() });
          return { status: "DELIVERED" };
        }),
      declinePlan: (id: string, planId: string) =>
        rec("declinePlan", [id, planId], () => {
          const p = (this.visible(id).plans ?? []).find((x) => x.id === planId);
          if (!p) throw new ApiError(404, { code: "NOT_FOUND" });
          p.status = "DECLINED";
          return { status: "DECLINED" };
        }),
      postTurn: (id: string, message: string, period?: ExplicitPeriod | null, action?: UiAction | null, clarification?: ClarificationReply | null, attachmentIds?: string[], clientRequestId?: string | null) => {
        this.requestIds.push(clientRequestId ?? null);
        this.calls.push({ method: "postTurn", args: attachmentIds && attachmentIds.length ? [id, message, period ?? null, action ?? null, clarification ?? null, attachmentIds] : clarification ? [id, message, period ?? null, action ?? null, clarification] : [id, message, period ?? null, action ?? null] });
        return new Promise<TurnResponse>((resolve, reject) => {
          try {
            const s = this.visible(id);
            if (s.investigation.status !== "ACTIVE") throw new ApiError(409, { code: "INVESTIGATION_NOT_ACTIVE" });
            if (this.failNextTurn) {
              const e = this.failNextTurn;
              this.failNextTurn = null;
              throw e;
            }
            s.messages.push({ id: uid("m"), role: "USER", kind: "TEXT", content: message, turn_id: null, created_at: ts() });
            this.pending = { id, message, period: period ?? null, action: action ?? null, clarification: clarification ?? null, resolve, reject };
          } catch (e) {
            reject(e);
          }
        });
      },
      resolve: (id: string, note: string) =>
        rec("resolve", [id, note], () => {
          const s = this.visible(id);
          if (s.investigation.status !== "ACTIVE") throw new ApiError(409, { code: "CANNOT_RESOLVE" });
          s.investigation.status = "RESOLVED";
          s.investigation.resolution_note = note;
          return { status: "RESOLVED" };
        }),
      reopen: (id: string) =>
        rec("reopen", [id], () => {
          const s = this.visible(id);
          if (s.investigation.status !== "RESOLVED") throw new ApiError(409, { code: "NOT_RESOLVED" }); // archived is visibility, not resolution
          const note = s.investigation.resolution_note;
          s.investigation.status = "ACTIVE"; // the note and all history are kept
          s.messages.push({ id: uid("m"), role: "SYSTEM", kind: "SYSTEM_NOTE", turn_id: null, created_at: ts(), content: `This investigation was reopened. Your earlier conclusion was: ${note}` });
          return { status: "ACTIVE" };
        }),
      archive: (id: string) =>
        rec("archive", [id], () => {
          const s = this.visible(id);
          s.investigation.status = "ARCHIVED";
          s.investigation.resolution_note = null;
          return { status: "ARCHIVED" };
        }),
      setAgentAttached: (id: string, agent: AgentCode, attached: boolean) =>
        rec("setAgentAttached", [id, agent, attached], () => {
          const s = this.visible(id);
          if (s.investigation.status !== "ACTIVE") throw new ApiError(409, { code: "INVESTIGATION_NOT_ACTIVE" });
          if (attached && !s.agents[agent] && this.availability[agent].status === "NOT_ENTITLED") throw new ApiError(409, { code: "AGENT_NOT_ENTITLED" });
          if (s.agents[agent] !== attached) {
            s.agents[agent] = attached;
            s.messages.push({
              id: uid("m"), role: "SYSTEM", kind: "SYSTEM_NOTE", turn_id: null, created_at: ts(),
              content: attached ? `${agent} was attached to this investigation.` : `${agent} was detached from this investigation. Its earlier findings remain as historical evidence; it will not be used for new work.`,
            });
          }
          return { agent, attached };
        }),
      getAttachmentImage: (id: string, attachmentId: string) => rec("getAttachmentImage", [id, attachmentId], () => `blob:fake-${attachmentId}`),
      performanceApi: createPerformanceApi(async () => null), // a card's Save is exercised in the performance tests with their own fake; the chat fakes never reach it
      imagesApi: createImagesApi(async () => null), // the image card's Add button is exercised in the M9 tests with their own fake
      historyApi: {
        history: (q) => rec("history", [q], () => this.historyFor(q)),
        version: (id: string) => rec("version", [id], () => this.history.versions?.[id] ?? this.failHistory()),
        compare: (a: string, b: string) => rec("compare", [a, b], () => this.history.compare ?? this.failHistory()),
        recommendations: (id: string) => rec("recommendations", [id], () => this.history.recommendations ?? this.failHistory()),
      },
      approveListing: (generationId: string) => rec("approveListing", [generationId], () => ({ approved: true, message: "Approved for use in Metrion; not published.", banner: null })),
      recordListingCopy: (generationId: string) => rec("recordListingCopy", [generationId], () => true),
      uploadAttachment: (id: string, file: File) =>
        rec("uploadAttachment", [id, file.name], (): UploadedAttachment => {
          this.visible(id);
          if (this.uploadFails) throw this.uploadFails;
          if (this.uploadFailsFor === file.name) throw new ApiError(500, { detail: "boom" });
          const up = { id: uid("a"), name: file.name };
          this.uploads.push(up);
          return { id: up.id, filename: file.name, type: "PDF", byteSize: file.size, status: "OK", note: null, table: this.uploadTable };
        }),
      getAvailability: () => rec("getAvailability", [], () => structuredClone(this.availability)),
      getPriceImpactForm: (sku?: string) => rec("getPriceImpactForm", [sku ?? null], () => structuredClone(this.priceForm)),
      getNewProductForm: (sku?: string) => rec("getNewProductForm", [sku ?? null], () => structuredClone(this.productForm)),
      saveInput: (body: SaveInputBody) => rec("saveInput", [body], () => { this.saved.push(body); return {}; }),
      streamEvents: (id: string, onEvent: (e: TurnEvent) => void, signal?: AbortSignal) => {
        this.calls.push({ method: "streamEvents", args: [id] });
        if (this.streamFails) return Promise.reject(new ApiError(503, "no stream"));
        return new Promise<void>((resolve) => {
          const s = { id, emit: onEvent, closed: false };
          this.streams.push(s);
          signal?.addEventListener("abort", () => {
            s.closed = true;
            resolve();
          });
        });
      },
      getNeeds: (id: string) =>
        rec("getNeeds", [id], () => {
          this.visible(id);
          return { items: structuredClone(this.needs.get(id) ?? []) };
        }),
      getMemory: () => rec("getMemory", [], () => ({ items: structuredClone(this.memory) })),
      forgetMemory: (id: string) =>
        rec("forgetMemory", [id], () => {
          const before = this.memory.length;
          this.memory = this.memory.filter((m) => m.id !== id);
          if (this.memory.length === before) throw new ApiError(404, { detail: "Not found" });
          return { forgotten: id };
        }),
      getSharedFindings: () =>
        rec("getSharedFindings", [], () => {
          if (this.sharedError) throw this.sharedError;
          return { items: structuredClone(this.shared), hidden: structuredClone(this.hiddenFindings), hiddenTotal: this.hiddenFindings.reduce((n, h) => n + h.count, 0) };
        }),
      forgetSharedFinding: (id: string) =>
        rec("forgetSharedFinding", [id], () => {
          const before = this.shared.length;
          this.shared = this.shared.filter((f) => f.id !== id);
          if (this.shared.length === before) throw new ApiError(404, { detail: "Not found" });
          return { forgotten: id };
        }),
      getHealth: () =>
        rec("getHealth", [], () => {
          if (this.healthError) throw this.healthError;
          return { entries: structuredClone(this.health) };
        }),
      getFlow: (id: string, turnId: string) =>
        rec("getFlow", [id, turnId], () => {
          this.visible(id);
          const f = this.flows.get(turnId);
          if (!f) throw new ApiError(404, { code: "NOT_FOUND" });
          return structuredClone(f);
        }),
    };
  }
}

/** A findings feed the test drives by hand: no timers, fully deterministic. `tick()` is one poll. */
export class ManualFeed {
  started = 0;
  stopped = 0;
  private active: FeedOptions | null = null;

  factory: FeedFactory = (options): FindingsFeed => {
    this.started += 1;
    this.active = options;
    return {
      stop: () => {
        this.stopped += 1;
        this.active = null;
      },
    };
  };

  get running(): boolean {
    return this.active !== null;
  }

  async tick(): Promise<void> {
    const o = this.active;
    if (!o) return;
    o.onFindings(await o.fetchFindings());
  }
}
