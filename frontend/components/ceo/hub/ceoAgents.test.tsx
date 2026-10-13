import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// The agents hang off the CEO on wires; the seller no longer removes or reconnects agents from the canvas.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

describe("agents on wires", () => {
  it("shows every agent connected to the CEO before any conversation exists, with no remove or detach control anywhere", async () => {
    mount();
    const canvas = await screen.findByTestId("agent-canvas");
    for (const code of ["CI", "CFO", "PI", "CMO"]) {
      expect(within(canvas).getByTestId(`agent-node-${code}`)).toHaveAttribute("data-state", "ATTACHED");
      expect(within(canvas).queryByTestId(`wire-${code}`)).not.toBeInTheDocument();
    }
    expect(within(canvas).queryByRole("button", { name: /^(Remove|Detach|Connect)/ })).not.toBeInTheDocument();
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
});
