import { describe, expect, it } from "vitest";
import type { AgentAvailability, CeoMessage, FindingRow, InvestigationDetail, TurnRow } from "@/lib/ceo";
import {
  actionLabel, canvasNodes, describeError, findingStatusView, groupFindings, hubStateOf, isHistorical, mergeFindings, messageView, nodeState, refLabel,
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
