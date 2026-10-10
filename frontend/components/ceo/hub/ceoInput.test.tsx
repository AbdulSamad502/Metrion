import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// Spec 6.34: the CEO asks for what it needs in the conversation, and the seller answers through the chat bar or by choosing.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const QUESTION = {
  version: 1, kind: "INPUT", slot: "shipping",
  options: [
    { key: "opt-0", label: "None (0), I confirm", kind: "RECOMMENDED" as const, reason: "You are sure it is zero" },
    { key: "opt-1", label: "Unknown", kind: "ALTERNATIVE" as const, reason: "Margins that depend on it will show as unavailable" },
    { key: "other", label: "Other", kind: "OTHER" as const, reason: "Type your answer in the chat bar" },
    { key: "cancel", label: "Cancel", kind: "CANCEL" as const, reason: "Stop asking; nothing will run" },
  ],
};

async function open() {
  const id = fake.seed({ id: "inv-1" });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  await user().click(await screen.findByTestId("open-drawer"));
  await user().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  await user().type(screen.getByLabelText("Ask the CEO"), "A competitor cut their price");
  await user().click(screen.getByRole("button", { name: "Send" }));
  fake.completeTurn({ route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "(8 of 11) What is the shipping cost per unit?", compositionMode: null, choices: QUESTION });
  await screen.findByTestId("decision-card");
}

describe("input questions", () => {
  it("shows the options, tells the seller to type in the chat bar, and has no inline text box (the chat bar is the answer box)", async () => {
    await open();
    expect(screen.getByTestId("card-option-opt-0")).toHaveTextContent("None (0), I confirm");
    expect(screen.getByTestId("card-option-opt-1")).toHaveTextContent("Unknown");
    expect(screen.getByText(/type your answer in the chat bar/i)).toBeInTheDocument();
    expect(screen.queryByTestId("card-option-other")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled();
    expect(screen.getByTestId("ceo-status")).toHaveTextContent("Needs your input");
  });

  it("choosing an option answers that question", async () => {
    await open();
    await user().click(screen.getByTestId("card-option-opt-1"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("Unknown");
    expect(args[4]).toMatchObject({ option: "opt-1" });
    fake.completeTurn({ answer: "ok" });
  });

  it("a typed answer goes through the same chat bar as every message, with no special client logic", async () => {
    await open();
    await user().type(screen.getByLabelText("Ask the CEO"), "49.50");
    await user().click(screen.getByRole("button", { name: "Send" }));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("49.50"); // sent as typed: the backend parses it against the question that was asked
    expect(args[4]).toBeUndefined();
    fake.completeTurn({ answer: "ok" });
  });

  it("Cancel stops the questions", async () => {
    await open();
    await user().click(screen.getByTestId("card-cancel"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[4]).toMatchObject({ option: "cancel" });
    fake.completeTurn({ answer: "Okay, I have stopped. Nothing was run and nothing was saved." });
  });
});
