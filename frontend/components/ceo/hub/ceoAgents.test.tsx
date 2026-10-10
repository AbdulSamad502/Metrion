import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// The agents hang off the CEO on wires; each wire (and each agent) has a Remove / Connect control. Removing stops NEW work only.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

describe("agents on wires", () => {
  it("shows every agent connected to the CEO before any conversation exists, with a wire control on each", async () => {
    mount();
    const canvas = await screen.findByTestId("agent-canvas");
    for (const code of ["CI", "CFO", "PI", "CMO"]) {
      expect(within(canvas).getByTestId(`agent-node-${code}`)).toHaveAttribute("data-state", "ATTACHED");
      expect(within(canvas).getByTestId(`wire-${code}`)).toHaveAccessibleName(`Detach ${code === "CFO" ? "CFO" : code === "CI" ? "Competitor Intelligence" : code === "PI" ? "Product Intelligence" : "Slim CMO"} from this investigation`);
    }
    expect(screen.getByTestId("connected-row")).toHaveTextContent("4/4 agents connected");
  });

  it("Remove then Connect on the wire: removing starts a conversation if none is open, detaches for future work only, and Connect wires it back", async () => {
    mount();
    const u = user();
    await u.click(await screen.findByTestId("wire-CFO"));
    await waitFor(() => expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "DETACHED"));
    expect(fake.count("createInvestigation")).toBe(1);
    expect(fake.calls.find((c) => c.method === "setAgentAttached")?.args.slice(1)).toEqual(["CFO", false]);
    expect(screen.getByTestId("agent-node-CFO")).toHaveTextContent("Removed: not used for new work");
    expect(screen.getByTestId("connected-row")).toHaveTextContent("3/4 agents connected");
    await u.click(screen.getByTestId("wire-CFO"));
    await waitFor(() => expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "ATTACHED"));
  });

  it("the Remove / Connect button on the agent itself does the same as its wire", async () => {
    mount();
    const u = user();
    const node = await screen.findByTestId("agent-node-CFO");
    await u.click(within(node).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "DETACHED"));
    await u.click(within(screen.getByTestId("agent-node-CFO")).getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(screen.getByTestId("agent-node-CFO")).toHaveAttribute("data-state", "ATTACHED"));
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
