import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { ClarificationCard } from "@/lib/ceo";
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
    { key: "opt-1", label: "Unknown", kind: "ALTERNATIVE" as const, reason: "Margins that depend on it will show as unavailable", skip: true },
    { key: "other", label: "Other", kind: "OTHER" as const, reason: "Type your answer in the chat bar" },
    { key: "back", label: "Back", kind: "BACK" as const, reason: "Change my previous answer" },
    { key: "cancel", label: "Cancel", kind: "CANCEL" as const, reason: "Stop asking; nothing will run" },
  ],
};

async function open(question: ClarificationCard = QUESTION as ClarificationCard) {
  const id = fake.seed({ id: "inv-1" });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  await user().click(await screen.findByTestId("open-drawer"));
  await user().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  await user().type(screen.getByLabelText("Ask the CEO"), "A competitor cut their price");
  await user().click(screen.getByRole("button", { name: "Send" }));
  fake.completeTurn({ route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "(8 of 11) What is the shipping cost per unit?", compositionMode: null, choices: question });
  await screen.findByTestId("decision-card");
}

describe("input questions", () => {
  it("shows the options, tells the seller to type in the chat bar, and has no inline text box (the chat bar is the answer box)", async () => {
    await open();
    expect(screen.getByTestId("card-option-opt-0")).toHaveTextContent("None (0), I confirm");
    expect(screen.getByTestId("card-skip")).toHaveTextContent("Skip · Unknown"); // the backend's own "unknown" option, offered as Skip and described honestly
    expect(screen.getByTestId("card-back")).toBeInTheDocument();
    expect(screen.getByTestId("card-progress")).toHaveTextContent("Question 8 of 11");
    expect(screen.getByText(/type your answer in the chat bar/i)).toBeInTheDocument();
    expect(screen.queryByTestId("card-option-other")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask the CEO")).toBeEnabled();
    expect(screen.getByTestId("ceo-status")).toHaveTextContent("Needs your input");
  });

  it("choosing an option stages it; Continue answers that question", async () => {
    await open();
    const u = user();
    const before = fake.calls.filter((c) => c.method === "postTurn").length;
    await u.click(screen.getByTestId("card-option-opt-0"));
    expect(fake.calls.filter((c) => c.method === "postTurn")).toHaveLength(before);
    await u.click(screen.getByTestId("card-continue"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("None (0), I confirm");
    expect(args[4]).toMatchObject({ option: "opt-0" });
    fake.completeTurn({ answer: "ok" });
  });

  it("Skip sends the backend's unknown option, so the thread says Unknown rather than hiding what was recorded", async () => {
    await open();
    await user().click(screen.getByTestId("card-skip"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("Unknown");
    expect(args[4]).toMatchObject({ option: "opt-1" });
    fake.completeTurn({ answer: "ok" });
  });

  it("Back asks the backend to step back one question; the client keeps no answers of its own", async () => {
    await open();
    await user().click(screen.getByTestId("card-back"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[4]).toMatchObject({ option: "back" });
    fake.completeTurn({ answer: "(7 of 11) What is the current price?" });
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

describe("the title steps of a complete-listing request (CMO N-05b, N-05t)", () => {
  const TITLE_Q = {
    version: 1, kind: "INPUT", slot: "seller_title",
    options: [
      { key: "opt-0", label: "Use “AquaNest bottle”", kind: "RECOMMENDED" as const, reason: "Your product name, as you gave it" },
      { key: "opt-1", label: "Write title options for me first (1 CMO unit)", kind: "ALTERNATIVE" as const, reason: "I write options, you choose one, then the listing is written from it" },
      { key: "other", label: "Other", kind: "OTHER" as const, reason: "Type your answer in the chat bar" },
      { key: "cancel", label: "Cancel", kind: "CANCEL" as const, reason: "Stop asking; nothing will run" },
    ],
  };
  it("offers writing title options first as a choice, and sends only the option key (no internal value)", async () => {
    await open(TITLE_Q as ClarificationCard);
    const u = user();
    await u.click(screen.getByTestId("card-option-opt-1"));
    await u.click(screen.getByTestId("card-continue"));
    await screen.findByTestId("processing");
    const args = fake.calls.filter((c) => c.method === "postTurn").at(-1)!.args as unknown[];
    expect(args[1]).toBe("Write title options for me first (1 CMO unit)");
    expect(args[4]).toMatchObject({ option: "opt-1" });
    expect(JSON.stringify(args)).not.toContain("__title_options__");
    fake.completeTurn({ answer: "ok" });
  });
  it("asks the seller to confirm a typed title as typed: confirming and changing are two separate choices", async () => {
    const CONFIRM = {
      version: 1, kind: "INPUT", slot: "_typed_title_ok",
      options: [
        { key: "opt-0", label: "Yes, use exactly this title", kind: "RECOMMENDED" as const, reason: "I will write from it as typed" },
        { key: "opt-1", label: "No, let me change it", kind: "ALTERNATIVE" as const, reason: "Type a different title" },
        { key: "other", label: "Other", kind: "OTHER" as const, reason: "Type your answer in the chat bar" },
        { key: "cancel", label: "Cancel", kind: "CANCEL" as const, reason: "Stop asking; nothing will run" },
      ],
    };
    await open(CONFIRM as ClarificationCard);
    expect(screen.getByTestId("card-option-opt-0")).toHaveTextContent("Yes, use exactly this title");
    expect(screen.getByTestId("card-option-opt-1")).toHaveTextContent("No, let me change it");
    const before = fake.calls.filter((c) => c.method === "postTurn").length;
    await user().click(screen.getByTestId("card-option-opt-0"));
    expect(fake.calls.filter((c) => c.method === "postTurn")).toHaveLength(before); // choosing only stages it; nothing is sent until Continue
  });
});
