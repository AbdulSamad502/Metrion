import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { CeoMessage, PlanView } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
beforeEach(() => { fake = new FakeCeo(); });

const HASH = "a1b2c3d4".repeat(8);
const SUMMARY = [
  "Plan: run The title options.",
  "Slim CMO (recommend-only) will write listing title options for steel bottle on Amazon. It writes text only and changes nothing on any marketplace.",
  "Quota effect: 1 CMO unit (one result), counted only for results that complete; a failed or refused result uses nothing.",
  "Nothing has run yet. It runs only after you press Approve on this card.",
].join("\n");
const COMPACT = [
  "Write listing titles for steel bottle on Amazon.",
  "Using: Brand: Acme; Capacity: 1 litre.",
  "Model: qwen3:8b (Metrion's own server).",
  "Cost: 1 CMO unit, only if it completes.",
  "Valid for 30 minutes.",
];
const plan = (over: Partial<PlanView> = {}): PlanView => ({
  id: "plan-1", status: "AWAITING_APPROVAL", planHash: HASH, plan: { summary_text: SUMMARY, title: "Write listing titles for steel bottle on Amazon", compact_lines: COMPACT }, createdAt: "2026-10-13T10:00:00.000Z", expiresAt: "2026-10-13T10:30:00.000Z",
  plannedTurnId: "t1", executionTurnId: null, viewerIsRequester: true, ...over,
});
const messages: CeoMessage[] = [
  { id: "m1", role: "USER", kind: "TEXT", content: "give me titles for my steel bottle", turn_id: "t1", created_at: "2026-10-13T10:00:00.000Z" },
  { id: "m2", role: "CEO", kind: "PLAN", content: "I have prepared a plan. Nothing runs until you press Approve on the card below; typing yes does not approve it.", turn_id: "t1", created_at: "2026-10-13T10:00:01.000Z" },
];
const turn = { id: "t1", route: "ACTION", route_key: "cmo.generate_title_sets", status: "PLANNED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-13T10:00:00.000Z", classifier_result: {} };

async function open(plans: PlanView[]) {
  const id = fake.seed({ id: "inv-1", messages: structuredClone(messages), turns: [turn] as never, plans });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
  const u = userEvent.setup();
  await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  return { u, id };
}

describe("CEO Hub: the plan card in the chat", () => {
  it("shows the stored plan exactly, with Approve and Decline only to the requester while it waits", async () => {
    await open([plan()]);
    const card = await screen.findByTestId("plan-card");
    expect(card).toHaveAttribute("data-status", "AWAITING_APPROVAL");
    const lines = within(card).getByTestId("plan-lines").textContent ?? "";
    expect(within(card).getByTestId("plan-lines").querySelectorAll("li").length).toBeLessThanOrEqual(5); // compact: a few short lines
    expect(lines).toContain("Write listing titles for steel bottle on Amazon");
    expect(lines).toContain("Cost: 1 CMO unit, only if it completes.");
    expect(lines).not.toContain("recommend-only"); // the long disclosure wording is behind Details
    expect(within(card).queryByTestId("plan-details")).toBeNull();
    expect(within(card).getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Decline" })).toBeEnabled();
    expect(within(card).getByTestId("plan-hash")).toHaveTextContent("a1b2c3d4");
    expect(within(card).queryByText(/Typing yes/)).toBeNull(); // stated once, in the chat message, not repeated on the card
  });

  it("Details opens the complete stored plan text and the full hash; closing hides it again", async () => {
    const { u } = await open([plan()]);
    const card = await screen.findByTestId("plan-card");
    await u.click(within(card).getByTestId("plan-details-toggle"));
    const details = within(card).getByTestId("plan-details");
    expect(details.textContent).toContain("Slim CMO (recommend-only) will write listing title options for steel bottle on Amazon");
    expect(details.textContent).toContain("Nothing has run yet. It runs only after you press Approve on this card.");
    expect(within(card).getByTestId("plan-hash-full")).toHaveTextContent(HASH);
    await u.click(within(card).getByTestId("plan-details-toggle"));
    expect(within(card).queryByTestId("plan-details")).toBeNull();
  });

  it("a decided plan shrinks to its title, so the plan text is not repeated in the conversation", async () => {
    await open([plan({ status: "APPROVED" })]);
    const card = await screen.findByTestId("plan-card");
    expect(within(card).getByTestId("plan-title")).toHaveTextContent("Write listing titles for steel bottle on Amazon");
    expect(within(card).queryByTestId("plan-lines")).toBeNull();
  });

  it("Approve sends the plan id and the plan hash, then the thread is re-read (the result is a stored message)", async () => {
    const { u } = await open([plan()]);
    await u.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fake.calls.find((c) => c.method === "approvePlan")?.args).toEqual(["inv-1", "plan-1", HASH]));
    expect(await screen.findByText("Here is what Slim CMO wrote for the plan you approved.")).toBeInTheDocument();
    expect(screen.getByTestId("plan-card")).toHaveAttribute("data-status", "APPROVED");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull(); // approved once: no second button
  });

  it("Decline calls the decline endpoint and nothing runs", async () => {
    const { u } = await open([plan()]);
    await u.click(await screen.findByRole("button", { name: "Decline" }));
    await waitFor(() => expect(screen.getByTestId("plan-card")).toHaveAttribute("data-status", "DECLINED"));
    expect(fake.calls.some((c) => c.method === "approvePlan")).toBe(false);
    expect(screen.getByText(/Declined: nothing was run, sent or used up/)).toBeInTheDocument();
  });

  it("a person who did not ask the question sees the plan but no buttons", async () => {
    await open([plan({ viewerIsRequester: false })]);
    const card = await screen.findByTestId("plan-card");
    expect(within(card).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Decline" })).toBeNull();
    expect(within(card).getByTestId("plan-not-requester")).toBeInTheDocument();
  });

  it.each(["APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED"])("a %s plan has no buttons", async (status) => {
    await open([plan({ status })]);
    const card = await screen.findByTestId("plan-card");
    expect(card).toHaveAttribute("data-status", status);
    expect(within(card).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("a refusal from the server is shown in plain words and the card stays as it was", async () => {
    const { u } = await open([plan()]);
    fake.store.get("inv-1")!.plans![0].planHash = "f".repeat(64); // the server's plan changed after the card was drawn
    await u.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/This plan changed, or the approval does not match it\. Nothing was run\./)).toBeInTheDocument();
  });

  it("typing yes in the chat bar sends a turn and never calls the approve endpoint", async () => {
    const { u } = await open([plan()]);
    const box = await screen.findByRole("textbox");
    await u.type(box, "yes{Enter}");
    await waitFor(() => expect(fake.calls.some((c) => c.method === "postTurn")).toBe(true));
    expect(fake.calls.some((c) => c.method === "approvePlan")).toBe(false);
  });

  it("a plan that cannot be matched says nothing ran and offers no buttons", async () => {
    await open([]);
    const card = await screen.findByTestId("plan-card");
    expect(card).toHaveAttribute("data-status", "UNKNOWN");
    expect(within(card).queryByRole("button")).toBeNull();
  });
});
