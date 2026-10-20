import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { CeoMessage, Presentation } from "@/lib/ceo";
import { FakeCeo, ManualFeed, finding } from "@/test-support/fakeCeo";

// "Key Insights" under a CEO answer: only from that answer's own saved results, verbatim; never invented, never when there is nothing structured.
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const msg = (over: Partial<CeoMessage> & Pick<CeoMessage, "role" | "content">): CeoMessage => ({ id: `m-${Math.random().toString(36).slice(2)}`, kind: over.role === "USER" ? "TEXT" : "ANSWER", turn_id: null, created_at: "2026-10-10T09:00:00.000Z", ...over });
const pres = (over: Partial<Presentation> = {}): Presentation => ({ version: 1, headline: "h", figures: [], facts: [], gaps: [], offers: [], ...over });

async function open(id: string) {
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  const u = userEvent.setup();
  if (!screen.queryByTestId("drawer")) await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

describe("Key Insights", () => {
  it("lists the saved facts of this answer's own findings, verbatim", async () => {
    const id = fake.seed({
      id: "inv-1", messages: [msg({ role: "USER", content: "q" }), msg({ id: "a1", role: "CEO", content: "Answer text.", turn_id: "t1" })],
      findings: [finding({ id: "f1", turn_id: "t1", source: "CI", action_key: "ci.x", status: "COMPLETE", presentation: pres({ facts: [{ label: "Saved fact", text: "as the backend wrote it", basis: "b" }] }) })],
    });
    await open(id);
    const box = await screen.findByTestId("key-insights");
    expect(within(box).getByText("Saved fact: as the backend wrote it")).toBeInTheDocument();
  });

  it("shows nothing (just the normal message) when the answer has no structured results, or they belong to another turn or are not complete", async () => {
    const id = fake.seed({
      id: "inv-2", messages: [msg({ role: "USER", content: "q" }), msg({ id: "a1", role: "CEO", content: "Plain answer.", turn_id: "t1" })],
      findings: [
        finding({ id: "f1", turn_id: "t2", source: "CI", action_key: "ci.x", status: "COMPLETE", presentation: pres({ facts: [{ label: "Other", text: "turn", basis: "b" }] }) }),
        finding({ id: "f2", turn_id: "t1", source: "CI", action_key: "ci.y", status: "PARTIAL", presentation: pres({ facts: [{ label: "Partial", text: "result", basis: "b" }] }) }),
      ],
    });
    await open(id);
    expect(await screen.findByText("Plain answer.")).toBeInTheDocument();
    expect(screen.queryByTestId("key-insights")).toBeNull();
    expect(screen.queryByTestId("progress-steps")).toBeNull(); // no live events: no checklist
  });
});
