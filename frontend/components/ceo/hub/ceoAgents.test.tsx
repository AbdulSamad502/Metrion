import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// The agents are cards in the left window, each with Connect / Remove; removing stops new work only.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

describe("agents panel", () => {
  it("shows every agent as a card before any conversation exists, with what it does and Remove for the ones you can use", async () => {
    mount();
    const panel = await screen.findByTestId("agents-panel");
    for (const code of ["CI", "CFO", "PI", "CMO"]) expect(within(panel).getByTestId(`agent-card-${code}`)).toHaveAttribute("data-state", "ATTACHED");
    expect(within(panel).getByTestId("agent-card-CFO")).toHaveTextContent("Connected");
    expect(within(panel).getByTestId("agent-card-CFO")).toHaveTextContent(/Reconciles settlements/);
    expect(within(panel).getByTestId("remove-CFO")).toBeEnabled();
  });

  it("Remove then Connect: removing starts a conversation if none is open, detaches for future work only, and Connect wires it back", async () => {
    mount();
    const u = user();
    await u.click(await screen.findByTestId("remove-CFO"));
    await waitFor(() => expect(screen.getByTestId("agent-card-CFO")).toHaveAttribute("data-state", "DETACHED"));
    expect(fake.count("createInvestigation")).toBe(1);
    expect(fake.calls.find((c) => c.method === "setAgentAttached")?.args.slice(1)).toEqual(["CFO", false]);
    expect(screen.getByTestId("agent-card-CFO")).toHaveTextContent("Its earlier results stay as history");
    await u.click(screen.getByTestId("connect-CFO"));
    await waitFor(() => expect(screen.getByTestId("agent-card-CFO")).toHaveAttribute("data-state", "ATTACHED"));
  });

  it("a locked agent has no button and says why; an agent you cannot use is shown as no access", async () => {
    fake.availability.CFO = { status: "NOT_ENTITLED", chatActions: 5 };
    fake.availability.PI = { status: "NOT_PERMITTED", chatActions: 0 };
    mount();
    const cfo = await screen.findByTestId("agent-card-CFO");
    await waitFor(() => expect(cfo).toHaveAttribute("data-state", "LOCKED"));
    expect(within(cfo).queryByRole("button")).not.toBeInTheDocument();
    expect(cfo).toHaveTextContent("Not on your current plan");
    expect(screen.getByTestId("agent-card-PI")).toHaveAttribute("data-state", "NO_ACCESS");
    expect(screen.queryByTestId("connect-PI")).not.toBeInTheDocument();
  });
});
