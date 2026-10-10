import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { Presentation } from "@/lib/ceo";
import { FakeCeo, ManualFeed, finding } from "@/test-support/fakeCeo";

// C7: the follow-up chips under a product-idea list, honest labelling of public-web content, and the memory panel grouped by who keeps what.
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const presentation = (title: string, items: string[]): Presentation => ({
  version: 1, headline: `${title} ready`, figures: [], facts: [], gaps: [], offers: [], artefacts: [{ title, items, note: "From public web sources and not verified." }],
});

async function openWith(title: string, items: string[]) {
  const id = fake.seed({ id: "inv-1", findings: [finding({ id: "fp", turn_id: "t0", source: "PI", action_key: "pi.report", status: "COMPLETE", presentation: presentation(title, items) })] });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  const u = userEvent.setup();
  if (!screen.queryByTestId("drawer")) await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  return u;
}

describe("follow-up chips", () => {
  it("offers 'Write titles for #n' and 'Is #n worth stocking?' for the first ideas and sends exactly that text", async () => {
    const u = await openWith("Product ideas found on the public web", ["Steel Bottle", "Yoga Mat", "Desk Lamp", "Phone Stand"]);
    const chips = within(await screen.findByTestId("idea-chips"));
    expect(chips.getAllByRole("button")).toHaveLength(6); // three ideas, two follow-ups each: the fourth idea has none
    expect(chips.queryByText("Write titles for #4")).not.toBeInTheDocument();
    await u.click(chips.getByText("Is #2 worth stocking?"));
    await waitFor(() => expect(fake.calls.find((c) => c.method === "postTurn")?.args[1]).toBe("Is #2 worth stocking?"));
  });

  it("does not offer chips under other content and labels public-web content as such, not as written from the seller's details", async () => {
    await openWith("Market trends: Marketplace news", ["Fee changes announced. Two outlets report revised fees."]);
    const art = await screen.findByTestId("artefact");
    expect(screen.queryByTestId("idea-chips")).not.toBeInTheDocument();
    expect(within(art).getByText(/Quoted from public web sources/)).toBeInTheDocument();
    expect(within(art).queryByText(/from the details you gave/)).not.toBeInTheDocument();
  });

  it("keeps the 'written from your details' label for content the CMO wrote for the seller", async () => {
    await openWith("Title options for Amazon", ["Steel Bottle 1L"]);
    expect(within(await screen.findByTestId("artefact")).getByText(/from the details you gave/)).toBeInTheDocument();
  });
});

describe("what I remember, per agent", () => {
  it("groups items under who keeps them: shared first, then each agent's own", async () => {
    fake.memory = [
      { id: "m1", label: "CMO: marketplaces you chose last time", value: "AMAZON", shared: false, agent: "CMO", basis: "CONFIRMED_DECISION", createdAt: new Date().toISOString() },
      { id: "m2", label: "Business name", value: "Zyquora", shared: true, agent: "CEO", basis: "SELLER_STATED", createdAt: new Date().toISOString() },
      { id: "m3", label: "CFO: GST basis you chose last time", value: "EXCLUSIVE", shared: false, agent: "CFO", basis: "CONFIRMED_DECISION", createdAt: new Date().toISOString() },
    ];
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const panel = await screen.findByTestId("memory-panel");
    const groups = within(panel).getAllByTestId(/^memory-group-/).map((g) => g.getAttribute("data-testid"));
    expect(groups).toEqual(["memory-group-SHARED", "memory-group-CFO", "memory-group-CMO"]);
    expect(within(screen.getByTestId("memory-group-CMO")).getByText("The CMO keeps privately")).toBeInTheDocument();
    expect(within(screen.getByTestId("memory-group-CMO")).getByTestId("memory-m1")).toBeInTheDocument();
  });
});
