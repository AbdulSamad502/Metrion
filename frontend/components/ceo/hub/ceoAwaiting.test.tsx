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
  sessionStorage.clear();
});

const at = "2026-10-12T09:00:00.000Z";
const user = (id: string, content: string) => ({ id, role: "USER" as const, kind: "TEXT" as const, content, turn_id: null, created_at: at });
const ceo = (id: string, content: string) => ({ id, role: "CEO" as const, kind: "ANSWER" as const, content, turn_id: null, created_at: at });

async function open(id: string) {
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  const u = userEvent.setup();
  await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

describe("a question the server stored but has not answered (page refreshed while a turn was running)", () => {
  it("is shown as still being answered, never idle and never failed, and is re-read until the answer arrives", async () => {
    const id = fake.seed({ id: "inv-1", title: "Margins", messages: [user("m1", "Where am I losing money?")] });
    await open(id);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "RUNNING");
    expect(screen.getByTestId("awaiting-answer")).toHaveTextContent("Your last question has no answer yet");
    expect(screen.getByTestId("awaiting-answer")).toHaveTextContent("It has not been reported as done");
    expect(screen.getByTestId("chat-status")).toHaveTextContent("Answering your last question…");
    expect(screen.queryByText("Failed")).toBeNull();
    fake.store.get(id)!.messages.push(ceo("m2", "Here is your answer."));  // the running turn finishes on the server
    expect(await screen.findByText("Here is your answer.", {}, { timeout: 8000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("awaiting-answer")).toBeNull());
    expect(screen.getByTestId("chat-status")).toHaveTextContent("Ready");
  }, 15000);

  it("is not claimed when the thread already ends with the CEO's answer", async () => {
    const id = fake.seed({ id: "inv-2", title: "Done", messages: [user("m1", "Hi"), ceo("m2", "Hello.")] });
    await open(id);
    expect(screen.queryByTestId("awaiting-answer")).toBeNull();
    expect(screen.getByTestId("execution-panel")).not.toHaveAttribute("data-status", "RUNNING");
  });
});

describe("a new message while another turn of this conversation is still running", () => {
  it("is told it was refused as a notice, and the running task is not shown as failed", async () => {
    const id = fake.seed({ id: "inv-3", title: "Busy", messages: [user("m1", "First"), ceo("m2", "Answer one.")] });
    await open(id);
    fake.failNextTurn = new ApiError(409, { code: "TURN_IN_PROGRESS" });
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Ask the CEO"), "Second question");
    await u.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/still answering your previous question/)).toBeInTheDocument();
    expect(screen.getByTestId("execution-panel")).not.toHaveAttribute("data-status", "FAILED");
    expect(screen.queryByText("Not sent")).toBeNull();
  });
});
