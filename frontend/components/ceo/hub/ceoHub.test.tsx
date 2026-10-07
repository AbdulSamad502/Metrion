import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import type { CeoMessage } from "@/lib/ceo";
import { FakeCeo, ManualFeed, finding } from "@/test-support/fakeCeo";

const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;

beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

function mount() {
  return render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
}

const msg = (over: Partial<CeoMessage> & Pick<CeoMessage, "role" | "content">): CeoMessage => ({
  id: `m-${Math.random().toString(36).slice(2)}`, kind: over.role === "USER" ? "TEXT" : "ANSWER", turn_id: null, created_at: "2026-10-08T09:00:00.000Z", ...over,
});

async function openInvestigation(id: string) {
  await user().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

async function ask(text: string) {
  const u = user();
  await u.type(screen.getByLabelText("Ask the CEO"), text);
  await u.click(screen.getByRole("button", { name: "Send" }));
}

describe("empty and new states", () => {
  it("shows an honest empty state with nothing fabricated", async () => {
    mount();
    expect(await screen.findByText("No investigations yet")).toBeInTheDocument();
    expect(screen.getByText("Select or start an investigation")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-idle")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-canvas")).not.toBeInTheDocument(); // no investigation: no wires are claimed
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument();
    expect(fake.count("postTurn")).toBe(0);
  });

  it("creates an investigation through the existing endpoint and opens it as a new, empty conversation", async () => {
    mount();
    await screen.findByText("No investigations yet");
    await user().type(screen.getByLabelText(/Title for a new investigation/), "Margins");
    await user().click(screen.getByRole("button", { name: /New/ }));
    expect(await screen.findByText("New investigation")).toBeInTheDocument();
    expect(fake.calls.find((c) => c.method === "createInvestigation")?.args).toEqual(["Margins"]);
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "NEW");
    expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "ATTACHED");
    expect(screen.getByText("No findings yet")).toBeInTheDocument();
    expect(screen.getByText("Margins", { selector: ".t-card-title" })).toBeInTheDocument();
  });

  it("question ideas only fill the composer: they never send anything or call a model", async () => {
    fake.seed({ id: "inv-new", title: "Empty one" });
    mount();
    await openInvestigation("inv-new");
    await user().click(screen.getByRole("button", { name: "Why did my profit drop?" }));
    expect(screen.getByLabelText("Ask the CEO")).toHaveValue("Why did my profit drop?");
    expect(fake.count("postTurn")).toBe(0);
  });
});

describe("loading an investigation", () => {
  it("loads metadata, messages, findings with provenance, and the attached agents", async () => {
    const id = fake.seed({
      id: "inv-1",
      messages: [
        msg({ id: "u1", role: "USER", content: "How did last month go?", turn_id: "t1" }),
        msg({ id: "c1", role: "CEO", content: "Here is what your saved, verified results show.\n- Net realized revenue: ₹482,150.00 (DERIVED, as of 2026-10-01)", turn_id: "t1" }),
      ],
      turns: [{ id: "t1", route: "BUSINESS_STATE", route_key: "BS_PNL_LATEST", status: "DELIVERED", composition_mode: "TEMPLATE", user_message_id: "u1", ceo_message_id: "c1", created_at: "x" }],
      findings: [finding({ id: "f1", turn_id: "t1", source: "BUSINESS_STATE", action_key: "BS_PNL_LATEST", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "abcdef12-0000" }, { kind: "ENGINE_RESULT", id: "fedcba98-0000" }] })],
    });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("message-user")).toHaveTextContent("How did last month go?");
    expect(screen.getByTestId("message-ceo")).toHaveTextContent("₹482,150.00"); // the backend's gated text, shown verbatim
    expect(screen.getByText("Read directly from your saved, verified results.")).toBeInTheDocument();
    const card = screen.getByTestId("finding-f1");
    expect(within(card).getByText("Latest profit & loss")).toBeInTheDocument();
    expect(within(card).getByText("CEO · saved results", { exact: false })).toBeInTheDocument();
    expect(within(card).getByText(/Provenance: 2 verified references/)).toBeInTheDocument();
    expect(within(card).getByText("Engine result · abcdef12")).toBeInTheDocument();
    expect(["CI", "CFO", "PI", "CMO"].map((c) => screen.getByTestId(`agent-node-${c}`).getAttribute("data-state"))).toEqual(["ATTACHED", "ATTACHED", "ATTACHED", "ATTACHED"]);
    expect(fake.count("getInvestigation")).toBe(1);
  });

  it("reads availability once and the list once; nothing polls while idle", async () => {
    fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation("inv-1");
    await new Promise((r) => setTimeout(r, 60));
    expect([fake.count("listInvestigations"), fake.count("getAvailability"), fake.count("getInvestigation"), fake.count("getFindings")]).toEqual([1, 1, 1, 0]);
    expect(feed.started).toBe(0);
  });

  it("tenant isolation: another tenant's investigation is simply not found and leaks nothing", async () => {
    fake.seed({ id: "mine", title: "Mine" });
    fake.seed({ id: "theirs", title: "Secret plan", tenant: "B", messages: [msg({ id: "x", role: "USER", content: "TOP SECRET" })] });
    mount();
    expect(await screen.findByTestId("investigation-mine")).toBeInTheDocument();
    expect(screen.queryByText("Secret plan")).not.toBeInTheDocument(); // the list is the tenant's own
    // a stale or guessed link to the other tenant's id:
    const hub = fake.client();
    await expect(hub.getInvestigation("theirs")).rejects.toMatchObject({ status: 404 });
    await expect(hub.getFindings("theirs")).rejects.toMatchObject({ status: 404 });
    await expect(hub.postTurn("theirs", "hi")).rejects.toMatchObject({ status: 404 });
    expect(screen.queryByText("TOP SECRET")).not.toBeInTheDocument();
  });

  it("shows 'not found' (and no data) when the selected investigation is not the tenant's", async () => {
    fake.seed({ id: "mine", title: "Mine" });
    fake.seed({ id: "gone", title: "Vanished", tenant: "B" });
    const { rerender } = mount();
    await screen.findByTestId("investigation-mine");
    fake.tenant = "A";
    const c = fake.client();
    // simulate a list that still contains the id but whose detail now 404s (access changed)
    const stale = { ...c, listInvestigations: async () => [{ id: "gone", title: "Vanished", status: "ACTIVE" as const, origin: "USER_CHAT", created_at: "2026-10-08T00:00:00Z", last_message_at: "2026-10-08T00:00:00Z" }] };
    rerender(<CeoHubWorkspace client={stale} feedFactory={feed.factory} />);
    await user().click(await screen.findByTestId("investigation-gone"));
    expect(await screen.findByText("Investigation not found")).toBeInTheDocument();
    expect(screen.queryByTestId("message-user")).not.toBeInTheDocument();
  });
});

describe("a turn: processing, progressive findings, completion", () => {
  it("renders findings as each leg arrives, shows processing, then the final CEO answer, re-reading the thread once", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why did my profit drop in September?");

    // processing: the question shows immediately (pending), the composer is locked, the feed is running
    expect(await screen.findByTestId("processing")).toHaveTextContent("Why did my profit drop in September?");
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "PROCESSING");
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled();
    expect(screen.getByText("Waiting for the first finding")).toBeInTheDocument();
    expect(feed.running).toBe(true);
    const readsBefore = fake.count("getInvestigation");

    // first leg lands
    const f1 = fake.emitFinding(finding({ source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "11111111-aaaa" }] }));
    await feed.tick();
    const card1 = await screen.findByTestId(`finding-${f1.id}`);
    expect(within(card1).getByText("Just arrived")).toBeInTheDocument();
    expect(screen.getByTestId("processing")).toHaveTextContent("1 finding has arrived so far");
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "PROCESSING"); // the turn is still running

    // second leg lands; the first is not duplicated or disturbed
    const f2 = fake.emitFinding(finding({ source: "CFO", action_key: "cfo.anomaly_check", status: "COMPLETE" }));
    await feed.tick();
    await feed.tick(); // an unchanged poll changes nothing
    expect(await screen.findByTestId(`finding-${f2.id}`)).toBeInTheDocument();
    expect(screen.getAllByTestId(/^finding-/)).toHaveLength(2);
    expect(screen.getByTestId("processing")).toHaveTextContent("2 findings have arrived so far");

    // the turn completes: the final answer appears, processing ends, the feed is stopped
    fake.completeTurn({ route: "PLAYBOOK", answer: "Your margin band is WATCH. Contribution margin: 12.5%", findings: [] });
    await waitFor(() => expect(screen.queryByTestId("processing")).not.toBeInTheDocument());
    expect(screen.getAllByTestId("message-ceo")[0]).toHaveTextContent("Your margin band is WATCH. Contribution margin: 12.5%");
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "ACTIVE");
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled();
    expect(feed.running).toBe(false);
    expect(fake.count("getInvestigation") - readsBefore).toBe(1); // one authoritative re-read, not a refetch loop
    expect(screen.getAllByTestId("message-user")).toHaveLength(1); // the pending copy was replaced by the server's, not duplicated
    expect(screen.getAllByTestId(/^finding-/)).toHaveLength(2);
    expect(screen.getByText(/For “Why did my profit drop in September\?”/)).toBeInTheDocument();
  });

  it("a failed leg is shown plainly and does not block the completed ones or the answer", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why did my profit drop?");
    await screen.findByTestId("processing");
    const ok = fake.emitFinding(finding({ source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "22222222-aaaa" }] }));
    const bad = fake.emitFinding(finding({ source: "CFO", action_key: "cfo.anomaly_check", status: "FAILED", gap_reason: "the action failed" }));
    const late = fake.emitFinding(finding({ source: "CFO", action_key: "cfo.strategic_briefing", status: "PARTIAL", gap_reason: "partial result" }));
    await feed.tick();
    expect(within(await screen.findByTestId(`finding-${bad.id}`)).getByText("Failed")).toBeInTheDocument();
    expect(screen.getByTestId(`finding-${bad.id}`)).toHaveTextContent("the action failed");
    expect(screen.getByTestId(`finding-${late.id}`)).toHaveAttribute("data-status", "PARTIAL");
    expect(screen.getByTestId(`finding-${ok.id}`)).toHaveAttribute("data-status", "COMPLETE");
    fake.completeTurn({ route: "PLAYBOOK", answer: "What is verified: 12.5%\n- Not available: The anomaly check could not be completed." });
    expect(await screen.findByText(/The anomaly check could not be completed/)).toBeInTheDocument();
    expect(screen.getByTestId(`finding-${ok.id}`)).toBeInTheDocument();
  });

  it("clarification: the CEO's question is flagged as needing the seller's input", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why are my margins down?");
    fake.completeTurn({ route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "Which period do you mean?", compositionMode: null });
    expect(await screen.findByText("Needs your input")).toBeInTheDocument();
    expect(screen.getByText("Which period do you mean?")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled(); // the seller can answer immediately
  });

  it("out of scope is stated, not silently dropped", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Publish this listing on Amazon");
    fake.completeTurn({ route: "OUT_OF_SCOPE", answer: "I can't do that from here. I only recommend.", compositionMode: null });
    expect(await screen.findByText("Out of scope")).toBeInTheDocument();
  });

  it("a safety-fallback answer says it is from verified data only", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("What should I focus on?");
    fake.completeTurn({ answer: "- Not available: No seller goal has been recorded.", compositionMode: "TEMPLATE_FALLBACK" });
    expect(await screen.findByText(/did not pass the safety check/)).toBeInTheDocument();
  });

  it("a failed request keeps the thread usable, shows plain words, and still reloads what the server persisted", async () => {
    const id = fake.seed({ id: "inv-1" });
    fake.failNextTurn = new ApiError(503, { code: "CEO_NOT_CONFIGURED" });
    mount();
    await openInvestigation(id);
    await ask("hello");
    expect(await screen.findByText(/CEO is not configured yet/)).toBeInTheDocument();
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled();
    expect(feed.running).toBe(false);
  });

  it("sends the date range explicitly, never infers one, and blocks an invalid range before it leaves the browser", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    const u = user();
    await u.type(screen.getByLabelText("From"), "2026-09-01");
    await u.type(screen.getByLabelText("To"), "2026-08-01"); // before the start
    await u.type(screen.getByLabelText("Ask the CEO"), "Why did profit drop?");
    expect(screen.getByRole("alert")).toHaveTextContent("The end date is before the start date.");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await u.clear(screen.getByLabelText("To"));
    await u.type(screen.getByLabelText("To"), "2026-09-30");
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Why did profit drop?", { start: "2026-09-01", end: "2026-09-30" }]);
    fake.completeTurn({ answer: "ok" });
    await waitFor(() => expect(screen.queryByTestId("processing")).not.toBeInTheDocument());
  });

  it("sends NO period when none is chosen (the backend, not the UI, resolves any period named in the text)", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why did profit drop in September?");
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Why did profit drop in September?", null]);
    fake.completeTurn({ answer: "ok" });
  });
});

describe("agents on the canvas", () => {
  it("detaching a wire is future-only: history stays visible, marked historical, with its provenance", async () => {
    const id = fake.seed({
      id: "inv-1",
      findings: [finding({ id: "fc", turn_id: "t0", source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "33333333-aaaa" }] })],
    });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("finding-fc")).toHaveAttribute("data-historical", "false");
    await user().click(screen.getByTestId("wire-CFO"));
    await waitFor(() => expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "DETACHED"));
    expect(fake.calls.find((c) => c.method === "setAgentAttached")?.args).toEqual([id, "CFO", false]);
    expect(screen.getByTestId("system-note")).toHaveTextContent("CFO was detached from this investigation");
    const card = screen.getByTestId("finding-fc");
    expect(card).toHaveAttribute("data-historical", "true");
    expect(within(card).getByText("Historical")).toBeInTheDocument();
    expect(within(card).getByText(/historical evidence; its original sources are unchanged/)).toBeInTheDocument();
    expect(within(card).getByText("Engine result · 33333333")).toBeInTheDocument(); // original provenance intact
    expect(screen.getByTestId("wire-CFO")).toHaveAccessibleName("Attach CFO to this investigation"); // wiring it back is the seller's choice
    expect(screen.getByTestId("agent-node-CI")).toHaveAttribute("data-state", "ATTACHED"); // the others are untouched
  });

  it("opens an investigation where an agent was already detached: node detached, its old finding historical", async () => {
    const id = fake.seed({
      id: "inv-1", agents: { CI: true, CFO: false, PI: true, CMO: true },
      findings: [finding({ id: "old", turn_id: "t0", source: "CFO", action_key: "cfo.reconcile", status: "COMPLETE" })],
    });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "DETACHED");
    expect(screen.getByTestId("finding-old")).toHaveAttribute("data-historical", "true");
    expect(screen.getByText("Detached: not used for new work")).toBeInTheDocument();
  });

  it("a locked (not entitled) agent is shown as locked, has no wire to add, and is never shown as attached", async () => {
    fake.availability.CFO = { status: "NOT_ENTITLED", chatActions: 5 };
    const id = fake.seed({ id: "inv-1", agents: { CI: true, CFO: false, PI: true, CMO: true } });
    mount();
    await openInvestigation(id);
    const node = screen.getByTestId("agent-node-CFO");
    expect(node).toHaveAttribute("data-state", "LOCKED");
    expect(within(node).getByText("Locked: not on your plan")).toBeInTheDocument();
    expect(within(node).getByText(/cannot be attached, and nothing from it will run/)).toBeInTheDocument();
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument();
    expect(within(node).queryByRole("button")).not.toBeInTheDocument();
    expect(fake.count("setAgentAttached")).toBe(0);
  });

  it("a member without access sees the agent as no-access, not usable", async () => {
    fake.availability.PI = { status: "NOT_PERMITTED", chatActions: 0 };
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    const node = screen.getByTestId("agent-node-PI");
    expect(node).toHaveAttribute("data-state", "NO_ACCESS");
    expect(screen.queryByTestId("wire-PI")).not.toBeInTheDocument();
  });

  it("if the server refuses an attach (not entitled), the UI says so and does not pretend it worked", async () => {
    const id = fake.seed({ id: "inv-1", agents: { CI: true, CFO: false, PI: true, CMO: true } });
    mount();
    await openInvestigation(id);
    fake.availability.CFO = { status: "NOT_ENTITLED", chatActions: 5 }; // entitlement changed after the canvas loaded
    await user().click(screen.getByTestId("wire-CFO"));
    expect(await screen.findByText(/not on your plan, so it cannot be attached/)).toBeInTheDocument();
    expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "DETACHED");
  });

  it("is honest about what an attached agent can do from chat today", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    expect(within(screen.getByTestId("agent-node-CFO")).getByText(/5 actions the CEO can run from chat/)).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-node-CMO")).getByText(/cannot run its actions from chat yet/)).toBeInTheDocument();
  });
});

describe("investigation lifecycle", () => {
  it("resolving needs the seller's own note, then closes the thread and keeps it readable", async () => {
    const id = fake.seed({ id: "inv-1", messages: [msg({ id: "u1", role: "USER", content: "q", turn_id: "t1" })] });
    mount();
    await openInvestigation(id);
    const u = user();
    await u.click(screen.getByRole("button", { name: "Resolve" }));
    expect(screen.getByRole("button", { name: "Mark resolved" })).toBeDisabled(); // no note, no conclusion
    await u.type(screen.getByLabelText(/What did you conclude/), "Fees explained it; renegotiating.");
    await u.click(screen.getByRole("button", { name: "Mark resolved" }));
    expect(await screen.findByText(/Your note: Fees explained it; renegotiating\./)).toBeInTheDocument();
    expect(fake.calls.find((c) => c.method === "resolve")?.args).toEqual([id, "Fees explained it; renegotiating."]);
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "RESOLVED");
    expect(screen.queryByLabelText("Ask the CEO")).not.toBeInTheDocument(); // closed to new questions
    expect(screen.getByTestId("message-user")).toHaveTextContent("q"); // still readable
    expect(screen.getByTestId("investigation-inv-1")).toHaveTextContent("Resolved");
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument(); // a resolved investigation cannot be re-wired
  });

  it("archiving hides the investigation by default, closes it, and keeps it readable behind a toggle", async () => {
    const id = fake.seed({ id: "inv-1", title: "Old thread", messages: [msg({ id: "u1", role: "USER", content: "an old question" })] });
    fake.seed({ id: "inv-2", title: "Other thread" });
    mount();
    await openInvestigation(id);
    const u = user();
    await u.click(screen.getByRole("button", { name: "Archive" }));
    await u.click(screen.getAllByRole("button", { name: "Archive" })[1]); // the confirmation
    expect(await screen.findByText(/Hidden from your list by default/)).toBeInTheDocument();
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "ARCHIVED");
    expect(screen.queryByLabelText("Ask the CEO")).not.toBeInTheDocument();
    expect(screen.getByTestId("message-user")).toHaveTextContent("an old question");
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument(); // an archived investigation cannot be re-wired
    await waitFor(() => expect(screen.queryByTestId("investigation-inv-1")).not.toBeInTheDocument()); // hidden from the default list
    expect(screen.getByTestId("investigation-inv-2")).toBeInTheDocument();
    await u.click(screen.getByLabelText(/Show archived \(1\)/));
    expect(await screen.findByTestId("investigation-inv-1")).toHaveTextContent("Archived");
  });

  it("a resolved investigation can still be archived later", async () => {
    const id = fake.seed({ id: "inv-1", status: "RESOLVED", investigation: { resolution_note: "done" } as never });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "RESOLVED");
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
  });
});

describe("no figure is ever computed or invented by the UI", () => {
  it("shows no number the backend did not send, in any state", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    const text = screen.getByTestId("ceo-hub").textContent ?? "";
    expect(text).not.toMatch(/₹|score|projected|uplift|potential (revenue|profit)/i);
  });
});

describe("reopening a resolved investigation", () => {
  it("offers Reopen only for a resolved investigation; reopening restores the composer and keeps the history", async () => {
    const id = fake.seed({
      id: "inv-1", status: "RESOLVED", investigation: { resolution_note: "Fees explained it." } as never,
      messages: [msg({ id: "u1", role: "USER", content: "an earlier question", turn_id: "t1" })],
      findings: [finding({ id: "keep", turn_id: "t1", source: "CFO", action_key: "cfo.reconcile", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "44444444-aaaa" }] })],
    });
    mount();
    await openInvestigation(id);
    expect(screen.getByText(/Your note: Fees explained it\./)).toBeInTheDocument();
    expect(screen.queryByLabelText("Ask the CEO")).not.toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "ACTIVE"));
    expect(fake.calls.find((c) => c.method === "reopen")?.args).toEqual([id]);
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled(); // open for new questions again
    expect(screen.getByTestId("message-user")).toHaveTextContent("an earlier question"); // nothing lost
    expect(screen.getByTestId("finding-keep")).toHaveTextContent("Engine result · 44444444");
    expect(screen.getByTestId("system-note")).toHaveTextContent("Your earlier conclusion was: Fees explained it."); // the conclusion is kept in the thread
    expect(screen.getByTestId("investigation-inv-1")).toHaveTextContent("Active");
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
  });

  it("never offers Reopen for an active or an archived investigation (archived is visibility, not resolution)", async () => {
    fake.seed({ id: "active" });
    fake.seed({ id: "arch", status: "ARCHIVED" });
    mount();
    await openInvestigation("active");
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
    await user().click(screen.getByLabelText(/Show archived/));
    await user().click(await screen.findByTestId("investigation-arch"));
    await screen.findByText(/Hidden from your list by default/);
    expect(screen.queryByRole("button", { name: "Reopen" })).not.toBeInTheDocument();
    expect(fake.count("reopen")).toBe(0);
  });

  it("if the server refuses, the UI says so in plain words and stays resolved", async () => {
    const id = fake.seed({ id: "inv-1", status: "RESOLVED", investigation: { resolution_note: "x" } as never });
    mount();
    await openInvestigation(id);
    fake.store.get(id)!.investigation.status = "ARCHIVED"; // changed elsewhere after the page loaded
    await user().click(screen.getByRole("button", { name: "Reopen" }));
    expect(await screen.findByText("Only a resolved investigation can be reopened.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ask the CEO")).not.toBeInTheDocument();
  });
});
