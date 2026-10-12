import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// Spec agent-memory.md: the seller can see everything the agents remember and forget any of it.
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

describe("what I remember", () => {
  it("says plainly when nothing is remembered yet", async () => {
    mount();
    await screen.findByTestId("agent-canvas");
    expect(screen.queryByTestId("memory-panel")).not.toBeInTheDocument(); // nothing remembered: no empty panel
  });

  it("shows each remembered item verbatim with whether it is shared, and forgets the one the seller removes", async () => {
    fake.memory = [
      { id: "m1", label: "Business name", value: "Zyquora", shared: true, agent: "CEO", basis: "SELLER_STATED", createdAt: new Date().toISOString() },
      { id: "m2", label: "Product Intelligence: last niche you researched", value: "mens shoes", shared: false, agent: "PI", basis: "CONFIRMED_DECISION", createdAt: new Date().toISOString() },
    ];
    mount();
    const first = await screen.findByTestId("memory-m1");
    expect(first).toHaveTextContent("Zyquora");
    expect(within(first).getByText("Shared")).toBeInTheDocument();
    expect(within(screen.getByTestId("memory-m2")).getByText("PI")).toBeInTheDocument(); // an agent's own note is labelled as that agent's
    await userEvent.setup().click(screen.getByRole("button", { name: "Forget Business name" }));
    await waitFor(() => expect(screen.queryByTestId("memory-m1")).not.toBeInTheDocument());
    expect(fake.calls.find((c) => c.method === "forgetMemory")?.args).toEqual(["m1"]);
    expect(screen.getByTestId("memory-m2")).toBeInTheDocument();
  });
});
