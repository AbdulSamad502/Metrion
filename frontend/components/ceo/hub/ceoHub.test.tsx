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

async function openList() {
  if (!screen.queryByTestId("drawer")) await user().click(await screen.findByTestId("open-drawer")); // the conversations live in the drawer
}

async function openAgent(code: string) {
  await screen.findByTestId(`agent-node-${code}`); // the remove / connect control is always on the agent's wire: nothing to open first
}

async function openInvestigation(id: string) {
  await openList();
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
    await openList();
    expect(await screen.findByText("No investigations yet")).toBeInTheDocument();
    expect(screen.getByTestId("welcome")).toBeInTheDocument(); // nothing selected: what the CEO can do, as things to click
    expect(screen.queryByTestId("canvas-idle")).not.toBeInTheDocument(); // the empty "nothing yet" blocks are not drawn; panels appear when they have something to show
    expect(screen.getByTestId("agent-canvas")).toBeInTheDocument(); // the agents are always shown; a new conversation connects all of them
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument();
    expect(fake.count("postTurn")).toBe(0);
  });

  it("creates an investigation through the existing endpoint and opens it as a new, empty conversation", async () => {
    mount();
    await openList();
    await screen.findByText("No investigations yet");
    await user().type(screen.getByLabelText(/Title for a new investigation/), "Margins");
    await user().click(within(screen.getByTestId("drawer")).getByRole("button", { name: /New/ })); // the list's own button (the canvas has a separate "New Investigation" one)
    expect(await screen.findByTestId("welcome")).toBeInTheDocument();
    expect(fake.calls.find((c) => c.method === "createInvestigation")?.args).toEqual(["Margins"]);
    expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "NEW");
    expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "ATTACHED");
    expect(screen.queryByText("No findings yet")).not.toBeInTheDocument();
    expect(screen.getByText("Margins", { selector: ".t-card-title" })).toBeInTheDocument();
  });

  it("a question idea asks that question (a catalog tile or an idea is one click), and a conversation starts by itself", async () => {
    mount();
    await user().click(await screen.findByRole("button", { name: "Why did my profit drop?" }));
    await screen.findByTestId("processing");
    expect(fake.count("createInvestigation")).toBe(1); // typing or clicking with no conversation open starts one
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([expect.any(String), "Why did my profit drop?", null, null]);
    fake.completeTurn({ answer: "ok" });
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
    await openList();
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
    await openList();
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
    await waitFor(() => expect(screen.getByTestId("ceo-status")).toHaveTextContent("Needs your input")); // the CEO node says so
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

  it("sends NO period when none is chosen (the backend, not the UI, resolves any period named in the text)", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why did profit drop in September?");
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Why did profit drop in September?", null, null]);
    fake.completeTurn({ answer: "ok" });
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
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled(); // closed to new questions
    expect(screen.getByTestId("message-user")).toHaveTextContent("q"); // still readable
    await openList();
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
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled();
    expect(screen.getByTestId("message-user")).toHaveTextContent("an old question");
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument(); // an archived investigation cannot be re-wired
    await openList();
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
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled();
    await user().click(screen.getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(screen.getByTestId("conversation")).toHaveAttribute("data-state", "ACTIVE"));
    expect(fake.calls.find((c) => c.method === "reopen")?.args).toEqual([id]);
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled(); // open for new questions again
    expect(screen.getByTestId("message-user")).toHaveTextContent("an earlier question"); // nothing lost
    expect(screen.getByTestId("finding-keep")).toHaveTextContent("Engine result · 44444444");
    expect(screen.getByTestId("system-note")).toHaveTextContent("Your earlier conclusion was: Fees explained it."); // the conclusion is kept in the thread
    await openList();
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
    await openList();
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
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------------------------- B5: figures, quick actions, health, flow
import type { HealthEntry, Presentation, TurnFlow } from "@/lib/ceo";

const snapshot = (over: Partial<Presentation> = {}): Presentation => ({
  version: 1,
  headline: "Net realized revenue: ₹4,82,150.00",
  figures: [
    { label: "Net realized revenue", value: "₹4,82,150.00", register: "DERIVED", as_of: "2026-09-30", note: null, ref: { kind: "ENGINE_RESULT", id: "abcdef12-0000" } },
    { label: "Contribution profit", value: "₹91,200.00", register: "ESTIMATE", as_of: null, note: "Based on a saved estimate.", ref: { kind: "ESTIMATE", id: "eeeeeeee-0000" } },
  ],
  facts: [{ label: "Band", text: "Watch", basis: "SOURCE_DERIVED" }],
  gaps: ["Marketplace fees are not uploaded yet."],
  offers: [{ key: "cfo.anomaly_check", label: "Check this period for unusual changes" }],
  ...over,
});

describe("the agents' responses show verified figures", () => {
  it("renders each figure verbatim with its register and as-of date, plus facts, gaps and offers; references stay one click away", async () => {
    const id = fake.seed({
      id: "inv-1",
      findings: [finding({ id: "f1", turn_id: "t1", source: "CFO", action_key: "cfo.financial_health", status: "PARTIAL", figure_refs: [{ kind: "ENGINE_RESULT", id: "abcdef12-0000" }], presentation: snapshot() })],
    });
    mount();
    await openInvestigation(id);
    const card = screen.getByTestId("finding-f1");
    const figures = within(card).getAllByTestId("figure");
    expect(figures[0]).toHaveTextContent("Net realized revenue");
    expect(within(figures[0]).getByTestId("figure-value").textContent).toBe("₹4,82,150.00"); // exactly the backend's formatting, untouched
    expect(within(figures[1]).getByTestId("figure-value").textContent).toBe("₹91,200.00");
    expect(figures[0]).toHaveTextContent("Derived from verified");
    expect(figures[0]).toHaveTextContent("as of 2026-09-30");
    expect(figures[1]).toHaveTextContent("Estimate"); // an estimate is never dressed as verified
    expect(figures[1]).toHaveTextContent("Based on a saved estimate.");
    expect(within(card).getByText("Marketplace fees are not uploaded yet.")).toBeInTheDocument();
    expect(within(card).getByText("Check this period for unusual changes")).toBeInTheDocument();
    expect(within(card).queryByText("Engine result · abcdef12")).not.toBeInTheDocument(); // collapsed
    await user().click(within(card).getByText(/Provenance: 1 verified reference/));
    expect(within(card).getByText("Engine result · abcdef12")).toBeInTheDocument();
  });

  it("an older finding without a snapshot still shows its status and references (nothing is invented)", async () => {
    fake.seed({ id: "inv-1", findings: [finding({ id: "old", turn_id: "t1", source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE", figure_refs: [{ kind: "ENGINE_RESULT", id: "99999999-0000" }] })] });
    mount();
    await openInvestigation("inv-1");
    const card = screen.getByTestId("finding-old");
    expect(within(card).queryByTestId("presentation")).not.toBeInTheDocument();
    expect(within(card).getByText("Engine result · 99999999")).toBeInTheDocument();
  });

  it("a refused leg shows the reason as a gap and no figure", async () => {
    fake.seed({
      id: "inv-1",
      findings: [finding({ id: "no", turn_id: "t1", source: "CFO", action_key: "cfo.anomaly_check", status: "DENIED", presentation: snapshot({ figures: [], facts: [], offers: [], gaps: ["You do not have access to this check."], headline: "You do not have access to this check." }) })],
    });
    mount();
    await openInvestigation("inv-1");
    const card = screen.getByTestId("finding-no");
    expect(within(card).queryAllByTestId("figure")).toHaveLength(0);
    expect(within(card).getByText("You do not have access to this check.")).toBeInTheDocument();
  });

});

describe("quick actions", () => {
  it("sends the chosen catalog item as an action (the label is the thread text) and nothing is typed", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await user().click(screen.getByTestId("quick-pnl"));
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Latest profit & loss", null, { kind: "BUSINESS_STATE", key: "BS_PNL_LATEST" }]);
    fake.completeTurn({ route: "BUSINESS_STATE", answer: "Here is your saved P&L.", compositionMode: "TEMPLATE" });
    await waitFor(() => expect(screen.queryByTestId("processing")).not.toBeInTheDocument());
    expect(screen.getByTestId("message-ceo")).toHaveTextContent("Here is your saved P&L.");
  });

  it("a period action is sent WITHOUT a period: the CEO asks for it in the conversation, no date control exists", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("quick-diagnosis")).toBeEnabled();
    await user().click(screen.getByTestId("quick-diagnosis"));
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Why did profit drop?", null, { kind: "PLAYBOOK", key: "PROFIT_DIAGNOSIS" }]);
    fake.completeTurn({ answer: "ok" });
  });

  it("a chip needing a detached agent is disabled and says why; the briefing, which needs none, stays available", async () => {
    fake.seed({ id: "inv-1", agents: { CI: true, CFO: false, PI: true, CMO: true } });
    mount();
    await openInvestigation("inv-1");
    expect(screen.getByTestId("quick-pnl")).toBeDisabled();
    expect(screen.getByTestId("quick-pnl")).toHaveAttribute("title", "CFO is not attached to this investigation.");
    expect(screen.getByTestId("quick-briefing")).toBeEnabled();
  });

  it("the chat bar is locked while a turn is running, and the backend's refusal is shown as the answer", async () => {
    fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation("inv-1");
    await user().click(screen.getByTestId("quick-bands"));
    await screen.findByTestId("processing");
    expect(screen.getByLabelText("Ask the CEO")).toBeDisabled(); // one question at a time
    fake.completeTurn({ status: "DENIED", route: "CLARIFY", answer: "That quick action is not available for this investigation." });
    expect(await screen.findByText("That quick action is not available for this investigation.")).toBeInTheDocument();
    expect(screen.getByText("Not permitted")).toBeInTheDocument();
  });
});

describe("turning an agent on", () => {
  it("a locked agent offers nothing to click, and no agent has a remove, detach or connect control on the canvas", async () => {
    const id = fake.seed({ id: "inv-1", agents: { CI: true, CFO: false, PI: false, CMO: true } });
    fake.availability.PI = { status: "NOT_ENTITLED", chatActions: 0 };
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("agent-node-PI").tagName).toBe("DIV"); // locked: nothing to click, never offered
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Remove|Detach|Connect)/ })).not.toBeInTheDocument();
  });
});

describe("business at a glance", () => {
  const entry = (over: Partial<HealthEntry>): HealthEntry => ({ key: "BS_HEALTH_BANDS", status: "COMPLETE", period: "2026-09", asOf: "2026-09-30", previewHint: null, presentation: snapshot(), ...over });

  it("shows each saved result with its own date; an unavailable result says so instead of showing a number", async () => {
    fake.health = [entry({}), entry({ key: "BS_PNL_LATEST", status: "UNAVAILABLE", period: null, asOf: null, presentation: null, previewHint: "No profit & loss has been saved yet." })];
    mount();
    await openList();
    expect(await screen.findByTestId("health-BS_HEALTH_BANDS")).toHaveTextContent("₹4,82,150.00");
    expect(screen.getByTestId("health-BS_PNL_LATEST")).toHaveTextContent("Not available yet");
    expect(screen.getByTestId("health-BS_PNL_LATEST")).toHaveTextContent("No profit & loss has been saved yet.");
    expect(screen.getByTestId("health-BS_PNL_LATEST").querySelector("[data-testid=figure]")).toBeNull();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument(); // no composite score exists
  });

  it("says nothing is saved yet (not that it is unavailable) when the request worked and returned no results", async () => {
    fake.health = [];
    mount();
    await openList();
    await screen.findByText("No investigations yet");
    expect(screen.queryByTestId("health-none-saved")).toBeNull(); // an empty, successful read draws nothing (an error still does, with a retry)
    expect(screen.queryByTestId("summary-cards")).toBeNull();
    expect(screen.queryByTestId("health-unavailable")).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  it("says plainly when the strip cannot be loaded, and lets the seller retry", async () => {
    fake.healthError = new ApiError(403, { code: "FORBIDDEN" });
    mount();
    await openList();
    expect(await screen.findByTestId("health-unavailable")).toBeInTheDocument();
    fake.healthError = null;
    fake.health = [entry({})];
    await user().click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("health-BS_HEALTH_BANDS")).toBeInTheDocument();
  });
});

describe("show flow", () => {
  const flow: TurnFlow = {
    turnId: "t1", route: "PLAYBOOK", routeKey: "PROFIT_DIAGNOSIS", routeSource: "UI_ACTION", status: "DELIVERED", compositionMode: "TEMPLATE", timings: null,
    ceo: { id: "r0", agentId: "CEO", triggerRef: null, status: "COMPLETE", permissionCheck: null, entitlementCheck: null, startedAt: null, finishedAt: null, reason: null },
    legs: [{ id: "r1", agentId: "CFO", triggerRef: "cfo.anomaly_check", status: "DENIED", permissionCheck: "DENIED:investigation.view", entitlementCheck: null, startedAt: null, finishedAt: null, reason: "not permitted" }],
  };

  async function openWithTurn() {
    const id = fake.seed({
      id: "inv-1",
      messages: [msg({ id: "u1", role: "USER", content: "Why did profit drop?", turn_id: "t1" })],
      turns: [{ id: "t1", route: "PLAYBOOK", route_key: "PROFIT_DIAGNOSIS", route_source: "UI_ACTION", status: "DELIVERED", composition_mode: "TEMPLATE", user_message_id: "u1", ceo_message_id: null, created_at: "x" }],
      findings: [finding({ id: "f1", turn_id: "t1", source: "CFO", action_key: "cfo.anomaly_check", status: "DENIED" })],
    });
    mount();
    await openInvestigation(id);
    return id;
  }

  it("loads the audit flow on demand, marks a quick action, and shows a refused leg with its reason", async () => {
    fake.flows.set("t1", flow);
    await openWithTurn();
    expect(fake.count("getFlow")).toBe(0); // nothing is fetched until asked
    expect(screen.getByText(/quick action/)).toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: "Show flow" }));
    const view = await screen.findByTestId("flow-view");
    expect(view).toHaveTextContent("You chose a quick action, so no model decided the route.");
    expect(view).toHaveTextContent("Anomaly check");
    expect(view).toHaveTextContent("Not permitted");
    expect(view).toHaveTextContent("not permitted");
    expect(fake.count("getFlow")).toBe(1);
  });

  it("a flow that cannot be read says so in plain words", async () => {
    await openWithTurn(); // no flow registered: the fake answers 404 like the server does for a foreign id
    await user().click(screen.getByRole("button", { name: "Show flow" }));
    expect(await screen.findByText("That investigation was not found.")).toBeInTheDocument();
  });
});

describe("live progress (SSE) is an accelerator over the poll, never a dependency", () => {
  it("shows what the turn is doing and fetches findings the moment a leg finishes, without waiting for a poll", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Why did profit drop?");
    await screen.findByTestId("processing");
    await waitFor(() => expect(fake.streams.length).toBe(1)); // the stream was opened with the turn
    const before = fake.count("getFindings");
    fake.streams[0].emit({ kind: "CLASSIFIED", atMs: 3, data: { route: "PLAYBOOK" } });
    expect(await screen.findByTestId("stage")).toHaveTextContent("Choosing what to check");
    expect(within(screen.getByTestId("progress-steps")).getAllByRole("listitem")).toHaveLength(1); // the checklist is the real stage words, nothing more
    fake.emitFinding(finding({ source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE" }));
    fake.streams[0].emit({ kind: "LEG_FINISHED", atMs: 9, data: { action: "cfo.financial_health", status: "COMPLETE" } });
    await waitFor(() => expect(fake.count("getFindings")).toBe(before + 1)); // fetched by the event: the manual feed never ticked
    expect(await screen.findByText("Financial health bands")).toBeInTheDocument();
    fake.completeTurn({ answer: "done" });
    await waitFor(() => expect(screen.queryByTestId("processing")).not.toBeInTheDocument());
  });

  it("closes the stream when the turn ends", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("hello");
    await waitFor(() => expect(fake.streams.length).toBe(1));
    fake.completeTurn({ answer: "ok" });
    await waitFor(() => expect(fake.streams[0].closed).toBe(true));
  });

  it("a stream that cannot open changes nothing: the turn completes through the normal path", async () => {
    fake.streamFails = true;
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("hello");
    await screen.findByTestId("processing");
    expect(screen.queryByTestId("stage")).not.toBeInTheDocument(); // no stage text, and no error either
    fake.emitFinding(finding({ source: "CFO", action_key: "cfo.financial_health", status: "COMPLETE" }));
    await feed.tick(); // the poll still delivers progressive findings
    expect(await screen.findByText("Financial health bands")).toBeInTheDocument();
    fake.completeTurn({ answer: "ok" });
    await waitFor(() => expect(screen.queryByTestId("processing")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a second question while one is running is refused in plain words", async () => {
    const id = fake.seed({ id: "inv-1" });
    fake.failNextTurn = new ApiError(409, { code: "TURN_IN_PROGRESS" });
    mount();
    await openInvestigation(id);
    await ask("hello");
    expect(await screen.findByText(/still answering your previous question/)).toBeInTheDocument();
  });
});

describe("the new quick actions", () => {
  it("send the specialist actions as catalog keys, and are disabled when their agent is detached", async () => {
    const id = fake.seed({ id: "inv-1", agents: { CI: false, CFO: true, PI: true, CMO: true } });
    mount();
    await openInvestigation(id);
    expect(screen.getByTestId("quick-competitors")).toBeDisabled();
    expect(screen.getByTestId("quick-competitors")).toHaveAttribute("title", "Competitor Intelligence is not attached to this investigation.");
    await user().click(screen.getByTestId("quick-report"));
    await screen.findByTestId("processing");
    expect(fake.calls.find((c) => c.method === "postTurn")?.args).toEqual([id, "Latest research report", null, { kind: "ACTION", key: "pi.report" }]);
    fake.completeTurn({ answer: "ok" });
  });
});

// ------------------------------------------------------------------------------------------------ C5: decision cards and conflicts
const CARD = {
  version: 1, kind: "MISSING_INPUT", slot: "period",
  options: [
    { key: "period-2026-09-01/2026-09-30", label: "September 2026", kind: "RECOMMENDED" as const, reason: "Latest period with saved results" },
    { key: "period-2026-08-01/2026-08-31", label: "August 2026", kind: "ALTERNATIVE" as const, reason: "An earlier period with saved results" },
    { key: "other", label: "Other", kind: "OTHER" as const, reason: "Type it in your own words" },
  ],
};

async function askForCard() {
  const id = fake.seed({ id: "inv-1" });
  mount();
  await openInvestigation(id);
  await ask("Why are my margins down?");
  fake.completeTurn({ route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "Which period do you mean?", compositionMode: null, choices: CARD });
  await screen.findByTestId("decision-card");
  return id;
}

describe("decision cards (spec 6.32)", () => {
  it("shows exactly the real options the backend sent, the recommended one first with its rule, and an Other; nothing is invented", async () => {
    await askForCard();
    const card = screen.getByTestId("decision-card");
    const options = within(card).getAllByRole("radio");
    expect(options.map((r) => r.closest("label")!.textContent)).toEqual(["September 2026RecommendedLatest period with saved results", "August 2026An earlier period with saved results", "Other…"]);
    expect(within(card).getByTestId("card-continue")).toBeDisabled(); // nothing is chosen for the seller
    expect(within(card).queryByTestId("card-back")).toBeNull(); // the backend offered no Back, so none is shown
    expect(within(card).queryByTestId("card-skip")).toBeNull();
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled(); // typing a plain answer still works
  });

  it("choosing an option sends that option's key with the card's id, and the label is the thread text", async () => {
    await askForCard();
    const cardId = (await screen.findAllByTestId("message-ceo")).length && fake.store.get("inv-1")!.messages.at(-1)!.id;
    const u = user();
    await u.click(screen.getByTestId("card-option-period-2026-08-01/2026-08-31"));
    expect(fake.calls.filter((c) => c.method === "postTurn")).toHaveLength(1); // choosing only stages the answer: the seller's own question is the only turn so far
    await u.click(screen.getByTestId("card-continue"));
    await screen.findByTestId("processing");
    expect(fake.calls.filter((c) => c.method === "postTurn").at(-1)?.args).toEqual([
      "inv-1", "August 2026", null, null, { id: cardId, option: "period-2026-08-01/2026-08-31" },
    ]);
    fake.completeTurn({ answer: "Here is August." });
  });

  it("Other sends the typed text with a null option; an empty answer cannot be sent", async () => {
    await askForCard();
    const u = user();
    await u.click(screen.getByTestId("card-option-other"));
    const field = screen.getByLabelText("Your own answer");
    const send = screen.getByTestId("card-continue");
    expect(send).toBeDisabled();
    await u.type(field, "   ");
    expect(send).toBeDisabled(); // blank is not an answer
    await u.clear(field);
    await u.type(field, "last quarter");
    await u.click(screen.getByTestId("card-option-period-2026-09-01/2026-09-30")); // changing their mind keeps what was typed
    await u.click(screen.getByTestId("card-option-other"));
    expect(screen.getByLabelText("Your own answer")).toHaveValue("last quarter");
    await u.click(screen.getByTestId("card-continue"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("last quarter");
    expect(args[4]).toMatchObject({ option: null });
    fake.completeTurn({ answer: "ok" });
  });

  it("an answered card is gone the moment the answer is sent, so it cannot be answered twice", async () => {
    await askForCard();
    const u = user();
    await u.click(screen.getByTestId("card-option-period-2026-09-01/2026-09-30"));
    await u.click(screen.getByTestId("card-continue"));
    await screen.findByTestId("processing");
    expect(screen.queryByTestId("decision-card")).not.toBeInTheDocument();
    fake.completeTurn({ answer: "Here is September." });
    expect(await screen.findByText("Here is September.")).toBeInTheDocument();
    expect(screen.queryByTestId("decision-card")).not.toBeInTheDocument();
  });

  it("a plain clarification with no real candidates shows no card", async () => {
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    await ask("Tell me about it");
    fake.completeTurn({ route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "What would you like to know?", compositionMode: null });
    expect(await screen.findByText("What would you like to know?")).toBeInTheDocument();
    expect(screen.queryByTestId("decision-card")).not.toBeInTheDocument();
  });

  it("a card in a resolved investigation cannot be answered", async () => {
    fake.seed({
      id: "inv-1", status: "RESOLVED",
      messages: [msg({ role: "CEO", kind: "CLARIFICATION", content: "Which period do you mean?", choices: CARD })],
    });
    mount();
    await openInvestigation("inv-1");
    expect(screen.queryByTestId("decision-card")).not.toBeInTheDocument();
  });
});

describe("conflicts are shown as the backend wrote them", () => {
  it("shows the backend's block verbatim, with neither value presented as a plain figure", async () => {
    const text = "Net realized revenue (2026-09-01/2026-09-30) has two different stored values: A, and B. They differ; neither has been chosen, averaged or combined.";
    fake.seed({
      id: "inv-1",
      findings: [finding({
        id: "fc", turn_id: "t1", source: "BUSINESS_STATE", action_key: "BS_PNL_LATEST", status: "COMPLETE",
        presentation: snapshot({ figures: [], facts: [], gaps: [], offers: [], headline: "Net realized revenue has two different stored values", conflicts: [{ what: "Net realized revenue", text, kind: "C1_METRIC", refIds: ["a", "b"] }] }),
      })],
    });
    mount();
    await openInvestigation("inv-1");
    const card = screen.getByTestId("finding-fc");
    expect(within(card).getByTestId("conflict").textContent).toBe(text);
    expect(within(card).queryAllByTestId("figure")).toHaveLength(0);
  });
});
