import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
let feed: ManualFeed;

beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

async function openConversation() {
  const id = fake.seed({ id: "inv-1", title: "Margins" });
  const client = fake.client();
  render(<CeoHubWorkspace client={client} feedFactory={feed.factory} />);
  if (!screen.queryByTestId("drawer")) await userEvent.setup().click(await screen.findByTestId("open-drawer"));
  await userEvent.setup().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  return client;
}

describe("a question that could not be sent", () => {
  it("is shown once, as not sent, when the backend cannot be reached and the thread cannot be refreshed", async () => {
    const client = await openConversation();
    fake.failNextTurn = new ApiError(503, {});
    client.getInvestigation = async () => {
      throw new TypeError("Failed to fetch"); // the backend is down: the refresh that would replace the local copy fails too
    };
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Ask the CEO"), "Where am I losing money?");
    await u.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Not sent")).toBeInTheDocument();
    expect(screen.queryByText("Sending…")).toBeNull(); // not "Sending…" forever
    expect(screen.getAllByText("Where am I losing money?")).toHaveLength(1); // one copy, not a duplicate
    expect(screen.queryByTestId("message-ceo")).toBeNull(); // and no answer was invented
  });
});

describe("a reply that was lost after the server accepted the question", () => {
  it("says the question was received and does not invite a resend (no second copy, no 'Not sent')", async () => {
    const client = await openConversation();
    const original = client.postTurn.bind(client);
    client.postTurn = async (...args: Parameters<typeof original>) => {
      const sent = original(...args);
      await Promise.resolve();
      fake.completeTurn({ answer: "Here is your answer." }); // the server finished and stored the turn...
      await sent;
      throw new TypeError("Failed to fetch"); // ...but the reply never reached the browser
    };
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Ask the CEO"), "Where am I losing money?");
    await u.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/reached the server, but its reply did not come back/)).toBeInTheDocument();
    expect(screen.getAllByText("Where am I losing money?")).toHaveLength(1);
    expect(screen.queryByText("Not sent")).toBeNull();
    expect(screen.getByText("Here is your answer.")).toBeInTheDocument(); // the stored answer is shown from the server's own thread
    expect(fake.count("postTurn")).toBe(1);
  });

  it("sends once when the send button is activated twice before the first request returns", async () => {
    await openConversation();
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Ask the CEO"), "Where am I losing money?");
    const send = screen.getByRole("button", { name: "Send" });
    await Promise.all([u.click(send), u.click(send), u.keyboard("{Enter}")]);
    expect(fake.count("postTurn")).toBe(1);
  });
});

describe("the identifier of one logical submission (clientRequestId)", () => {
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  async function ask(text: string) {
    const u = userEvent.setup();
    const box = screen.getByLabelText("Ask the CEO");
    await u.clear(box);
    await u.type(box, text);
    await u.click(screen.getByRole("button", { name: "Send" }));
  }

  // the send is over (the question that got no answer is no longer "Sending…") and the screen accepts the next one
  const failed = (n: number) => waitFor(() => {
      expect(fake.count("postTurn")).toBe(n);
      expect(screen.queryByText("Sending…")).toBeNull();
    });

  it("sends a UUID with every submission", async () => {
    await openConversation();
    await ask("Where am I losing money?");
    expect(fake.requestIds).toHaveLength(1);
    expect(fake.requestIds[0]).toMatch(UUID);
  });

  it("reuses the same id when the same question is sent again after it got no answer", async () => {
    await openConversation();
    fake.failNextTurn = new ApiError(503, {});
    await ask("Where am I losing money?");
    await failed(1);
    await ask("Where am I losing money?");
    expect(fake.requestIds).toHaveLength(2);
    expect(fake.requestIds[1]).toBe(fake.requestIds[0]);
  });

  it("uses a new id for different text after a failure, and for identical text after an answered send", async () => {
    await openConversation();
    fake.failNextTurn = new ApiError(503, {});
    await ask("Where am I losing money?");
    await failed(1);
    await ask("Which SKU loses most?"); // a different question is a different submission
    fake.completeTurn({ answer: "Here is your answer." });
    await screen.findByText("Here is your answer.");
    await ask("Which SKU loses most?"); // answered once: asking it again is a genuinely new submission
    expect(fake.requestIds).toHaveLength(3);
    expect(new Set(fake.requestIds).size).toBe(3);
  });
});
