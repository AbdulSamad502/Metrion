import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// The agents hang off the CEO on wires; the seller removes one with the small x on its card and reconnects it with the + that replaces it.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

describe("agents on wires", () => {
  it("shows every agent connected to the CEO before any conversation exists, each with a small remove control", async () => {
    mount();
    const canvas = await screen.findByTestId("agent-canvas");
    for (const code of ["CI", "CFO", "PI", "CMO"]) {
      expect(within(canvas).getByTestId(`agent-node-${code}`)).toHaveAttribute("data-state", "ATTACHED");
      expect(within(canvas).queryByTestId(`wire-${code}`)).not.toBeInTheDocument();
    }
    for (const code of ["CI", "CFO", "PI", "CMO"]) expect(within(canvas).getByTestId(`remove-${code}`)).toHaveAccessibleName(/^Remove .* from the CEO/);
    expect(screen.getByTestId("connected-row")).toHaveTextContent("4/4 connected");
  });

  it("a locked agent has no wire control and says why; an agent you cannot use is shown as no access", async () => {
    fake.availability.CFO = { status: "NOT_ENTITLED", chatActions: 5 };
    fake.availability.PI = { status: "NOT_PERMITTED", chatActions: 0 };
    mount();
    const cfo = await screen.findByTestId("agent-node-CFO");
    await waitFor(() => expect(cfo).toHaveAttribute("data-state", "LOCKED"));
    expect(within(cfo).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("wire-CFO")).not.toBeInTheDocument();
    expect(cfo).toHaveTextContent("Not available on your current plan");
    expect(screen.getByTestId("agent-node-PI")).toHaveAttribute("data-state", "NO_ACCESS");
    expect(screen.queryByTestId("wire-PI")).not.toBeInTheDocument();
  });

  it("the x removes an agent and a + puts it back", async () => {
    mount();
    const canvas = await screen.findByTestId("agent-canvas");
    await user().click(within(canvas).getByTestId("remove-CI"));
    await waitFor(() => expect(within(canvas).getByTestId("agent-node-CI")).toHaveAttribute("data-state", "DETACHED"));
    expect(within(canvas).queryByTestId("remove-CI")).not.toBeInTheDocument();
    await user().click(within(canvas).getByTestId("attach-CI"));
    await waitFor(() => expect(within(canvas).getByTestId("agent-node-CI")).toHaveAttribute("data-state", "ATTACHED"));
  });
});
