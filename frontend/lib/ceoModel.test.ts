import { describe, expect, it } from "vitest";
import type { AgentAvailability, CeoMessage, FindingRow, InvestigationDetail, TurnRow } from "@/lib/ceo";
import {
  actionLabel, approvalRefused, canvasNodes, describeError, findingStatusView, groupFindings, hubStateOf, isHistorical, mergeFindings, messageView, nodeState, refLabel,
  validatePeriod, visibleInvestigations, withPendingMessage,
} from "@/lib/ceoModel";

const avail = (over: Partial<AgentAvailability> = {}): AgentAvailability => ({
  CI: { status: "PRESENT", chatActions: 0 }, CFO: { status: "PRESENT", chatActions: 5 }, PI: { status: "PRESENT", chatActions: 0 },
  CMO: { status: "PRESENT", chatActions: 0 }, ...over,
});
const f = (id: string, createdAt: string, over: Partial<FindingRow> = {}): FindingRow => ({
  id, source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE", figure_refs: [], report_ref: null, gap_reason: null, agent_run_id: null, created_at: createdAt, ...over,
});

describe("node states (what a wire means)", () => {
  it("never presents an unknown, locked or no-access agent as attached", () => {
    expect(nodeState(true, avail(), "CFO")).toBe("ATTACHED");
    expect(nodeState(false, avail(), "CFO")).toBe("DETACHED");
    expect(nodeState(undefined, null, "CFO")).toBe("UNKNOWN");
    expect(nodeState(true, avail({ CFO: { status: "NOT_ENTITLED", chatActions: 5 } }), "CFO")).toBe("LOCKED"); // even if a stale row says attached
    expect(nodeState(false, avail({ CFO: { status: "NOT_ENTITLED", chatActions: 5 } }), "CFO")).toBe("LOCKED");
    expect(nodeState(true, avail({ CFO: { status: "NOT_PERMITTED", chatActions: 5 } }), "CFO")).toBe("NO_ACCESS");
  });

  it("only attached or detached agents of an ACTIVE investigation can be toggled", () => {
    const agents = { CI: true, CFO: false, PI: true, CMO: true };
    const nodes = canvasNodes(agents, avail({ PI: { status: "NOT_ENTITLED", chatActions: 0 } }), "ACTIVE");
    expect(nodes.map((n) => [n.code, n.state, n.canToggle])).toEqual([["CI", "ATTACHED", true], ["CFO", "DETACHED", true], ["PI", "LOCKED", false], ["CMO", "ATTACHED", true]]);
    expect(canvasNodes(agents, avail(), "RESOLVED").every((n) => !n.canToggle)).toBe(true);
    expect(canvasNodes(agents, avail(), "ARCHIVED").every((n) => !n.canToggle)).toBe(true);
    expect(canvasNodes(null, null, null).every((n) => n.state === "UNKNOWN" && !n.canToggle)).toBe(true);
  });

  it("uses the product's agent names", () => {
    expect(canvasNodes({}, null, "ACTIVE").map((n) => n.name)).toEqual(["Competitor Intelligence", "CFO", "Product Intelligence", "Slim CMO"]);
  });
});

describe("findings", () => {
  it("merges by id, never rewrites a known finding, and orders oldest first", () => {
    const a = f("a", "2026-10-08T09:00:01Z");
    const c = f("c", "2026-10-08T09:00:03Z");
    const b = f("b", "2026-10-08T09:00:02Z");
    const once = mergeFindings([a], [c, b]);
    expect(once.map((x) => x.id)).toEqual(["a", "b", "c"]);
    const rewritten = mergeFindings(once, [{ ...a, status: "FAILED" }]);
    expect(rewritten).toBe(once); // same instance: nothing new, so no re-render
    expect(rewritten[0].status).toBe("COMPLETE"); // append-only: the stored finding is not overwritten by a later copy
  });

  it("groups findings under the question that produced them, newest question first", () => {
    const messages: CeoMessage[] = [
      { id: "m1", role: "USER", kind: "TEXT", content: "First question", turn_id: "t1", created_at: "2026-10-08T09:00:00Z" },
      { id: "m2", role: "USER", kind: "TEXT", content: "Second question", turn_id: "t2", created_at: "2026-10-08T09:05:00Z" },
    ];
    const turns: TurnRow[] = [
      { id: "t1", route: "PLAYBOOK", route_key: "PROFIT_DIAGNOSIS", status: "DELIVERED", composition_mode: "LLM", user_message_id: "m1", ceo_message_id: null, created_at: "x" },
      { id: "t2", route: "ACTION", route_key: null, status: "DELIVERED", composition_mode: "LLM", user_message_id: "m2", ceo_message_id: null, created_at: "y" },
    ];
    const groups = groupFindings([f("a", "2026-10-08T09:00:01Z", { turn_id: "t1" }), f("b", "2026-10-08T09:05:01Z", { turn_id: "t2" }), f("c", "2026-10-08T09:05:02Z", { turn_id: "t2" })], messages, turns);
    expect(groups.map((g) => [g.question, g.findings.map((x) => x.id)])).toEqual([["Second question", ["b", "c"]], ["First question", ["a"]]]);
  });

  it("puts a finding that arrived before its turn row under the in-flight question", () => {
    const groups = groupFindings([f("a", "2026-10-08T09:00:01Z", { turn_id: "not-loaded-yet" })], [], [], "Why did profit drop?");
    expect(groups[0].question).toBe("Why did profit drop?");
  });

  it("marks a finding historical only when its agent is currently detached", () => {
    expect(isHistorical(f("a", "x", { source: "CFO" }), { CFO: false })).toBe(true);
    expect(isHistorical(f("a", "x", { source: "CFO" }), { CFO: true })).toBe(false);
    expect(isHistorical(f("a", "x", { source: "BUSINESS_STATE" }), { CFO: false })).toBe(false);
    expect(isHistorical(f("a", "x"), null)).toBe(false);
  });

  it("labels statuses plainly and keeps unknown ones visible", () => {
    expect(findingStatusView("FAILED")).toEqual({ label: "Failed", tone: "negative" });
    expect(findingStatusView("NOT_ENTITLED").label).toBe("Not on your plan");
    expect(findingStatusView("SOMETHING_NEW").label).toBe("SOMETHING_NEW");
    expect(actionLabel("cfo.cash_reconciliation")).toBe("Cash reconciliation");
    expect(actionLabel("BS_LEAK_OPEN")).toBe("Open leak findings");
    expect(actionLabel("cfo.something_new")).toBe("Something new");
    expect(refLabel({ kind: "ENGINE_RESULT", id: "12345678-aaaa" })).toBe("Engine result · 12345678");
  });
});

describe("messages and hub state", () => {
  const turn = (over: Partial<TurnRow>): TurnRow => ({ id: "t", route: "ADVISORY", route_key: null, status: "DELIVERED", composition_mode: "LLM", user_message_id: "u", ceo_message_id: "c", created_at: "x", ...over });
  const ceo = (over: Partial<CeoMessage>): CeoMessage => ({ id: "c", role: "CEO", kind: "ANSWER", content: "x", turn_id: "t", created_at: "x", ...over });

  it("labels clarifications, out-of-scope, denied and fallback answers", () => {
    const t = (x: TurnRow) => new Map([[x.id, x]]);
    expect(messageView(ceo({ kind: "CLARIFICATION" }), t(turn({}))).badge).toBe("Needs your input");
    expect(messageView(ceo({}), t(turn({ route: "OUT_OF_SCOPE" }))).badge).toBe("Out of scope");
    expect(messageView(ceo({}), t(turn({ status: "DENIED" }))).badge).toBe("Not permitted");
    expect(messageView(ceo({}), t(turn({ status: "FAILED" }))).badge).toBe("Could not complete");
    expect(messageView(ceo({}), t(turn({ composition_mode: "TEMPLATE_FALLBACK" }))).footnote).toMatch(/did not pass the safety check/);
    expect(messageView(ceo({}), t(turn({ composition_mode: "TEMPLATE" }))).footnote).toMatch(/saved, verified results/);
    expect(messageView(ceo({ role: "SYSTEM", kind: "SYSTEM_NOTE" }), new Map()).tone).toBe("note");
    expect(messageView(ceo({ role: "USER", kind: "TEXT" }), new Map()).tone).toBe("user");
  });

  const detail = (status: "ACTIVE" | "RESOLVED" | "ARCHIVED", withUser: boolean): InvestigationDetail => ({
    investigation: { id: "i", title: null, status, origin: "USER_CHAT", created_at: "x", last_message_at: "x", resolution_note: null, resolved_at: null, summary: null },
    agents: {}, turns: [], findings: [],
    messages: withUser ? [{ id: "m", role: "USER", kind: "TEXT", content: "q", turn_id: null, created_at: "x" }] : [],
  });

  it("derives the hub state without inventing one", () => {
    const base = { selectedId: "i", status: "ready" as const, processing: false };
    expect(hubStateOf({ ...base, selectedId: null, detail: null })).toBe("NO_SELECTION");
    expect(hubStateOf({ ...base, status: "loading", detail: null })).toBe("LOADING");
    expect(hubStateOf({ ...base, status: "notfound", detail: null })).toBe("NOT_FOUND");
    expect(hubStateOf({ ...base, status: "error", detail: null })).toBe("ERROR");
    expect(hubStateOf({ ...base, detail: detail("ACTIVE", false) })).toBe("NEW");
    expect(hubStateOf({ ...base, detail: detail("ACTIVE", true) })).toBe("ACTIVE");
    expect(hubStateOf({ ...base, detail: detail("ACTIVE", true), processing: true })).toBe("PROCESSING");
    expect(hubStateOf({ ...base, detail: detail("RESOLVED", true), processing: true })).toBe("RESOLVED");
    expect(hubStateOf({ ...base, detail: detail("ARCHIVED", true) })).toBe("ARCHIVED");
    expect(hubStateOf({ ...base, status: "error", detail: detail("ACTIVE", true) })).toBe("ACTIVE"); // a quiet refresh failure keeps what was loaded
  });

  it("hides archived investigations by default", () => {
    const items = ["ACTIVE", "RESOLVED", "ARCHIVED"].map((status, i) => ({ id: String(i), title: null, status, origin: "USER_CHAT", created_at: "x", last_message_at: "x" })) as never[];
    expect(visibleInvestigations(items, false)).toHaveLength(2);
    expect(visibleInvestigations(items, true)).toHaveLength(3);
  });

  it("flags the sent message as pending until the server's copy replaces it", () => {
    const out = withPendingMessage([], "hello", "2026-10-08T09:00:00Z");
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ role: "USER", content: "hello", pending: true });
  });
});

describe("date range guard (the backend re-validates)", () => {
  it("accepts none or a complete, started, ordered range", () => {
    expect(validatePeriod("", "", "2026-10-08")).toBeNull();
    expect(validatePeriod("2026-09-01", "2026-09-30", "2026-10-08")).toBeNull();
    expect(validatePeriod("2026-09-01", "", "2026-10-08")).toMatch(/both/);
    expect(validatePeriod("", "2026-09-30", "2026-10-08")).toMatch(/both/);
    expect(validatePeriod("2026-09-30", "2026-09-01", "2026-10-08")).toMatch(/before/);
    expect(validatePeriod("2026-11-01", "2026-11-30", "2026-10-08")).toMatch(/not started/);
  });
});

describe("errors", () => {
  it("speaks plainly and never leaks internals", () => {
    expect(describeError(409, { code: "AGENT_NOT_ENTITLED" })).toMatch(/not on your plan/);
    expect(describeError(422, { code: "INVALID_PERIOD" })).toMatch(/date range/);
    expect(describeError(503, { code: "CEO_NOT_CONFIGURED" })).toMatch(/not configured/);
    expect(describeError(404, "anything")).toMatch(/not found/);
    expect(describeError(500, { stack: "secret trace" })).toBe("Could not reach the backend.");
    expect(describeError(null, null)).toBe("Could not reach the backend.");
  });
});

// ---------------------------------------------------------------------------------------------- B5: presentation, quick actions, flow
import type { Presentation, TurnFlow } from "@/lib/ceo";
import { asOfLabel, flowSteps, hasPresentation, nodeResult, QUICK_ACTIONS, quickActionState, registerView, routeSourceLabel } from "@/lib/ceoModel";

const pres = (over: Partial<Presentation> = {}): Presentation => ({ version: 1, headline: "Net revenue: shown", figures: [], facts: [], gaps: [], offers: [], ...over });

describe("presentation helpers", () => {
  it("a finding has something to show only when its snapshot has content", () => {
    expect(hasPresentation(f("a", "1"))).toBe(false); // an old finding without a snapshot: references only
    expect(hasPresentation(f("a", "1", { presentation: pres() }))).toBe(false);
    expect(hasPresentation(f("a", "1", { presentation: pres({ gaps: ["Nothing saved yet."] }) }))).toBe(true);
  });

  it("never lets an unknown register look verified", () => {
    expect(registerView("VERIFIED").label).toBe("Verified");
    expect(registerView("ESTIMATE").tone).toBe("warning");
    expect(registerView("SOMETHING_NEW")).toEqual({ label: "SOMETHING_NEW", tone: "neutral" });
  });

  it("shows the as-of date exactly as stored, and nothing when there is none", () => {
    expect(asOfLabel("2026-09-30T00:00:00+00:00")).toBe("as of 2026-09-30");
    expect(asOfLabel(null)).toBeNull();
  });

  const fig = { label: "Margin", value: "shown", register: "DERIVED", as_of: null, note: null, ref: { kind: "ENGINE_RESULT", id: "x" } };
  const good = (headline: string) => pres({ headline, figures: [fig] });

  it("the node headline is the newest COMPLETE usable finding, with its own timestamp", () => {
    const rows = [
      f("a", "2026-10-01T00:00:00Z", { presentation: good("old") }),
      f("b", "2026-10-02T00:00:00Z", { presentation: good("new") }),
      f("c", "2026-10-03T00:00:00Z", { source: "PI", presentation: good("pi") }),
    ];
    expect(nodeResult(rows, "CFO")).toEqual({ headline: "new", headlineAt: "2026-10-02T00:00:00Z", newer: null, noCompleteResult: false });
    expect(nodeResult(rows, "PI").headline).toBe("pi");
  });

  it("a newer partial / failed / refused / unavailable result NEVER replaces an older complete one; it is reported beside it", () => {
    for (const status of ["PARTIAL", "FAILED", "DENIED", "UNAVAILABLE", "NOT_ENTITLED"] as const) {
      const rows = [
        f("old", "2026-10-01T00:00:00Z", { presentation: good("Margin: shown") }),
        f("new", "2026-10-05T00:00:00Z", { status, action_key: "cfo.anomaly_check", presentation: pres({ headline: "not enough history", gaps: ["not enough history"] }) }),
      ];
      expect(nodeResult(rows, "CFO"), status).toEqual({
        headline: "Margin: shown", headlineAt: "2026-10-01T00:00:00Z",
        newer: { status, at: "2026-10-05T00:00:00Z", label: "Anomaly check" }, noCompleteResult: false,
      });
    }
  });

  it("a COMPLETE finding whose snapshot holds only a gap sentence, or none, is not a usable result", () => {
    const rows = [
      f("a", "2026-10-01T00:00:00Z", { presentation: good("real") }),
      f("b", "2026-10-02T00:00:00Z", { presentation: pres({ headline: "just a gap", gaps: ["just a gap"] }) }),
      f("c", "2026-10-03T00:00:00Z"), // complete but written before snapshots existed
    ];
    expect(nodeResult(rows, "CFO").headline).toBe("real");
    expect(nodeResult(rows, "CFO").newer?.at).toBe("2026-10-03T00:00:00Z");
  });

  it("when no finding is complete and usable, the node says there is no complete result (never an incomplete one as the result)", () => {
    const rows = [f("a", "2026-10-02T00:00:00Z", { status: "PARTIAL", presentation: pres({ headline: "partial thing", figures: [fig] }) })];
    expect(nodeResult(rows, "CFO")).toEqual({
      headline: null, headlineAt: null, newer: { status: "PARTIAL", at: "2026-10-02T00:00:00Z", label: "Financial health bands" }, noCompleteResult: true,
    });
  });

  it("an agent with no findings at all makes no claim", () => {
    expect(nodeResult([], "CFO")).toEqual({ headline: null, headlineAt: null, newer: null, noCompleteResult: false });
    expect(nodeResult([f("a", "2026-10-01T00:00:00Z", { source: "PI", presentation: good("pi") })], "CMO").noCompleteResult).toBe(false);
  });

  it("the canvas carries that result per agent", () => {
    const rows = [f("a", "2026-10-01T00:00:00Z", { presentation: good("old") })];
    expect(canvasNodes({ CFO: true }, avail(), "ACTIVE", rows).find((n) => n.code === "CFO")?.result.headline).toBe("old");
  });
});

describe("quick actions", () => {
  const byId = (id: string) => QUICK_ACTIONS.find((q) => q.id === id)!;
  const period = { start: "2026-09-01", end: "2026-09-30" };

  it("every chip names a real catalog kind and a key (the backend refuses anything else)", () => {
    for (const q of QUICK_ACTIONS) {
      expect(["BUSINESS_STATE", "ACTION", "PLAYBOOK"]).toContain(q.action.kind);
      expect(q.action.key).toBeTruthy();
    }
  });

  it("a period-dependent chip is unavailable until the seller chooses a period (dates are never guessed)", () => {
    expect(quickActionState(byId("diagnosis"), { CFO: true }, null)).toEqual({ enabled: false, reason: "Choose a period first: the CEO never guesses dates." });
    expect(quickActionState(byId("diagnosis"), { CFO: true }, period).enabled).toBe(true);
    expect(quickActionState(byId("pnl"), { CFO: true }, null).enabled).toBe(true); // a saved-result read needs no period
  });

  it("a chip whose agent is detached or unknown is unavailable, with the reason", () => {
    expect(quickActionState(byId("pnl"), { CFO: false }, null)).toEqual({ enabled: false, reason: "CFO is not attached to this investigation." });
    expect(quickActionState(byId("pnl"), null, null).enabled).toBe(false);
  });
});

describe("flow", () => {
  const flow: TurnFlow = {
    turnId: "t", route: "PLAYBOOK", routeKey: "PROFIT_DIAGNOSIS", routeSource: "UI_ACTION", status: "DELIVERED", compositionMode: "TEMPLATE",
    timings: { stages: { route_resolution: { startMs: 10, endMs: 12 } } },
    ceo: { id: "r0", agentId: "CEO", triggerRef: null, status: "COMPLETE", permissionCheck: null, entitlementCheck: null, startedAt: null, finishedAt: null, reason: null },
    legs: [
      { id: "r1", agentId: "CFO", triggerRef: "cfo.financial_health", status: "COMPLETE", permissionCheck: "PASS", entitlementCheck: "PASS", startedAt: null, finishedAt: null, reason: null },
      { id: "r2", agentId: "CFO", triggerRef: "cfo.anomaly_check", status: "DENIED", permissionCheck: "DENIED:investigation.view", entitlementCheck: null, startedAt: null, finishedAt: null, reason: "not permitted" },
    ],
  };

  it("lists the CEO step then every leg, a refused leg included, with its reason", () => {
    const steps = flowSteps(flow);
    expect(steps.map((s) => [s.title, s.status])).toEqual([["CEO", "Completed"], ["Financial health bands", "Completed"], ["Anomaly check", "Not permitted"]]);
    expect(steps[0].detail).toBe("Ran a playbook · 2 ms");
    expect(steps[2].detail).toContain("not permitted");
  });

  it("says plainly whether a model or the seller's own click chose the route", () => {
    expect(routeSourceLabel("UI_ACTION")).toMatch(/no model/);
    expect(routeSourceLabel("CLASSIFIER")).toMatch(/model classified/);
  });
});

import { sourceLabel, stageLabel } from "@/lib/ceoModel";

describe("live progress and the new actions", () => {
  it("every known event kind has plain words, and an unknown one adds nothing", () => {
    for (const k of ["TURN_RECEIVED", "CLASSIFIED", "LEG_STARTED", "LEG_FINISHED", "STATE_READ", "SYNTHESIS_STARTED", "ANSWER_READY"]) expect(stageLabel(k)).toBeTruthy();
    expect(stageLabel("TURN_DONE")).toBeNull();
    expect(stageLabel("SOMETHING_NEW")).toBeNull();
  });

  it("the new actions and state entries have readable labels, and the GST lookup is named as its own source", () => {
    expect(actionLabel("gst_lookup")).toBe("GST rate lookup");
    expect(actionLabel("service.gst_lookup")).toBe("GST rate lookup");
    expect(actionLabel("ci.request_price_scenario")).toBe("Competitor price comparison");
    expect(actionLabel("BS_COMPETITOR_SNAPSHOT")).toBe("Competitor prices");
    expect(sourceLabel("GST_LOOKUP")).toBe("GST lookup");
  });

  it("each specialist chip needs its own agent attached and no period", () => {
    const need = Object.fromEntries(QUICK_ACTIONS.filter((q) => ["competitors", "research", "report", "listing"].includes(q.id)).map((q) => [q.id, [q.needsAgent, q.needsPeriod]]));
    expect(need).toEqual({ competitors: ["CI", false], research: ["PI", false], report: ["PI", false], listing: ["CMO", false] });
  });
});

describe("messageView reflects the stored outcome of a delivered turn", () => {
  const msg = { id: "m", role: "CEO", kind: "ANSWER", content: "x", turn_id: "t", created_at: "2026-10-11T00:00:00Z" } as never;
  const turn = (outcome: string | null) => new Map([["t", { id: "t", route: "PLAYBOOK", route_key: null, status: "DELIVERED", outcome, composition_mode: null, user_message_id: "u", ceo_message_id: "m", created_at: "2026-10-11T00:00:00Z" } as never]]);
  it("badges a delivered answer whose required step failed or is waiting for the seller", () => {
    expect(messageView(msg, turn("FAILED")).badge).toBe("Could not complete");
    expect(messageView(msg, turn("PENDING_INPUT")).badge).toBe("Waiting for your input");
    expect(messageView(msg, turn("PARTIAL")).badge).toBe("Partly completed");
  });
  it("adds no badge for a success, a declined reply or a legacy turn", () => {
    for (const o of ["SUCCEEDED", "DECLINED", null]) expect(messageView(msg, turn(o)).badge).toBeNull();
  });
});

describe("approval refusal label", () => {
  const turn = (over: Record<string, unknown>) => ({ id: "t", route: "ADVISORY", route_key: null, status: "DENIED", composition_mode: null, user_message_id: "u", ceo_message_id: "c", created_at: "2026-10-10T10:00:00Z", ...over }) as never;
  const ceoMsg = { id: "m", role: "CEO", kind: "ANSWER", content: "x", turn_id: "t", created_at: "2026-10-10T10:00:00Z" } as never;
  it("labels a DENIED turn as needing an approved plan only when the backend recorded the approval refusal", () => {
    const refused = turn({ classifier_result: { approvalRequiredFor: "pi.discover" } });
    expect(approvalRefused(refused)).toBe(true);
    expect(messageView(ceoMsg, new Map([["t", refused]])).badge).toBe("Needs an approved plan");
  });
  it("keeps 'Not permitted' for an ordinary denial and never infers approval from other states", () => {
    for (const t of [turn({}), turn({ classifier_result: {} }), turn({ classifier_result: { approvalRequiredFor: null } }), turn({ status: "FAILED", classifier_result: { approvalRequiredFor: "pi.discover" } })]) {
      expect(approvalRefused(t)).toBe(false);
    }
    expect(messageView(ceoMsg, new Map([["t", turn({})]])).badge).toBe("Not permitted");
  });

  it("does not trigger from approval-related wording in the message text or reason when the structured field is absent", () => {
    const words = { ...(ceoMsg as object), content: "This needs an approved plan before it can run. Approval is required." } as never;
    const t = turn({ classifier_result: { reason: "approval required" } });
    expect(approvalRefused(t)).toBe(false);
    expect(messageView(words, new Map([["t", t]])).badge).toBe("Not permitted");
  });

  it("shows no refusal label for turns that were not denied, even if the field is somehow present", () => {
    for (const status of ["DELIVERED", "CLARIFIED", "FAILED", "PLANNED"]) {
      const t = turn({ status, classifier_result: { approvalRequiredFor: "pi.discover" } });
      expect(approvalRefused(t)).toBe(false);
      expect(messageView(ceoMsg, new Map([["t", t]])).badge).not.toBe("Needs an approved plan");
    }
  });

  it("tolerates missing or null data without throwing", () => {
    expect(approvalRefused(undefined)).toBe(false);
    expect(approvalRefused(null)).toBe(false);
    expect(approvalRefused(turn({ classifier_result: null }))).toBe(false);
    expect(() => messageView(ceoMsg, new Map())).not.toThrow(); // the turn row is not loaded yet
  });

  it("never says the action ran or was approved", () => {
    const v = messageView(ceoMsg, new Map([["t", turn({ classifier_result: { approvalRequiredFor: "pi.discover" } })]]));
    expect(v.badge).toBe("Needs an approved plan");
    expect(v.footnote).toMatch(/not available yet, so nothing was run/);
    expect(`${v.badge} ${v.footnote}`).not.toMatch(/approved(?! plan)|granted|completed|ran successfully/i);
  });
});

describe("nodeState without availability", () => {
  it("never reports an agent as connected before availability is known, whatever the conversation says", () => {
    expect(nodeState(true, null, "CFO")).toBe("UNKNOWN");
    expect(nodeState(false, null, "CFO")).toBe("UNKNOWN");
    expect(nodeState(undefined, null, "CFO")).toBe("UNKNOWN");
  });
});


describe("saved-results question keys read as plain words (found in practical acceptance: the Task status showed Qt leaks)", () => {
  it("labels every business-state question the CEO can answer and never leaks a QT_ key", () => {
    for (const key of ["QT_AGENT_FINDINGS", "QT_COMPETITORS_PRICES", "QT_DATA_GAPS", "QT_GOALS", "QT_LEAKS", "QT_LISTING_CONTENT", "QT_NOT_STORED", "QT_PRODUCT_IDEAS", "QT_PROFIT_BY_PERIOD", "QT_SELLER_FACTS"]) {
      const label = actionLabel(key);
      expect(label).not.toMatch(/^Qt|QT_|_/);
      expect(label.length).toBeGreaterThan(5);
    }
    expect(actionLabel("QT_LEAKS")).toBe("Where money is leaking");
  });
});
