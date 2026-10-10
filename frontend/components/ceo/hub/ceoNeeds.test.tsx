import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { CeoMessage, NeedRow } from "@/lib/ceo";
import { needStepView } from "@/lib/ceoModel";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// S6a: the CEO's follow-up lookups (broker needs) shown as plain steps with the turn that produced them.
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const msg = (over: Partial<CeoMessage> & Pick<CeoMessage, "id" | "role" | "content">): CeoMessage => ({
  kind: over.role === "USER" ? "TEXT" : "ANSWER", turn_id: null, created_at: "2026-10-08T09:00:00.000Z", ...over,
});
const need = (over: Partial<NeedRow> & Pick<NeedRow, "id" | "status">): NeedRow => ({
  needKey: "GST_RATE_FOR_PRODUCT", requesterAgent: "CMO", providerKey: "service.gst_lookup", createdAt: "2026-10-08T09:00:01.000Z", turnMessageId: "a1", ...over,
});

async function open(needs: NeedRow[]) {
  const id = fake.seed({ id: "inv-1", messages: [msg({ id: "u1", role: "USER", content: "Write a description" }), msg({ id: "a1", role: "CEO", content: "Here is your description." })] });
  fake.needs.set(id, needs);
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  const u = userEvent.setup();
  if (!screen.queryByTestId("drawer")) await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

const OUTCOMES: [NeedRow["status"], RegExp][] = [
  ["FULFILLED", /Done/],
  ["REUSED", /earlier/],
  ["DENIED", /Not available to you/],
  ["NOT_ATTACHED", /turned off/],
  ["NOT_ENTITLED", /plan does not include it/],
  ["UNAVAILABLE", /Not available right now/],
  ["FAILED", /could not be completed/],
  ["TIMED_OUT", /took too long/],
  ["CONFIG_MISSING", /Not configured/],
  ["OFFERED", /Offered/],
  ["DROPPED", /Left out/],
];

describe("follow-up lookup steps", () => {
  it.each(OUTCOMES)("shows who asked whom for what and the outcome in plain words (%s)", async (status, outcome) => {
    await open([need({ id: "n1", status })]);
    const step = await screen.findByTestId("need-step-n1");
    expect(step).toHaveTextContent("The Slim CMO asked the GST lookup for the GST rate.");
    expect(within(step).getByText(outcome)).toBeInTheDocument();
    expect(step).toHaveAttribute("data-status", status);
  });

  it("places the step with the message that produced it, not elsewhere", async () => {
    await open([need({ id: "n1", status: "FULFILLED", turnMessageId: "a1" })]);
    const step = await screen.findByTestId("need-step-n1");
    const row = step.closest("ol > li");
    expect(within(row as HTMLElement).getByText("Here is your description.")).toBeInTheDocument();
    expect(screen.getAllByTestId("need-steps")).toHaveLength(1);
  });

  it("still shows a step whose message is not in the thread, after the thread", async () => {
    await open([need({ id: "n9", status: "DENIED", turnMessageId: "gone" })]);
    expect(await screen.findByTestId("need-step-n9")).toBeInTheDocument();
  });

  it("shows no step block when there are no lookups, and the conversation works if the read fails", async () => {
    await open([]);
    expect(screen.queryByTestId("need-steps")).not.toBeInTheDocument();
  });

  it("names the CFO route and an unknown key without guessing", () => {
    expect(needStepView(need({ id: "n", status: "FULFILLED", requesterAgent: "CEO", providerKey: "cfo.gst_lookup" })).text).toBe("The CEO asked the CFO's GST lookup for the GST rate.");
    expect(needStepView(need({ id: "n", status: "WEIRD", needKey: "SOMETHING_NEW" })).text).toContain("SOMETHING_NEW");
  });
});
