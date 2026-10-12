import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { CeoMessage } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
beforeEach(() => { fake = new FakeCeo(); });

const REFUSAL = "That would use up part of your plan or send what you typed to an outside service, so it has to be approved first.";
const turn = (cr: unknown) => ({ id: "t1", route: "ADVISORY", route_key: null, status: "DENIED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-11T10:00:00.000Z", classifier_result: cr });
const messages = (answer: string): CeoMessage[] => [
  { id: "m1", role: "USER", kind: "TEXT", content: "find trending products", turn_id: "t1", created_at: "2026-10-11T10:00:00.000Z" },
  { id: "m2", role: "CEO", kind: "ANSWER", content: answer, turn_id: "t1", created_at: "2026-10-11T10:00:01.000Z" },
];

async function open(id: string) {
  render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
  const u = userEvent.setup();
  await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  return await screen.findByTestId("conversation");
}

describe("CEO Hub: a refused approval-required request", () => {
  it("labels the answer and the task panel as needing an approved plan, and nothing says it ran or was approved", async () => {
    const id = fake.seed({ id: "inv-1", messages: messages(REFUSAL), turns: [turn({ approvalRequiredFor: "pi.discover" })] as never });
    const conv = await open(id);
    expect(within(conv).getByText("Needs an approved plan")).toBeInTheDocument();
    expect(within(conv).getByText(REFUSAL)).toBeInTheDocument();
    expect(within(screen.getByTestId("execution-panel")).getAllByText("Needs an approved plan").length).toBeGreaterThan(0);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "APPROVAL_REQUIRED");
    expect(screen.queryByText(/approved and run|was approved|completed/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull(); // no approval control exists before the backend plan workflow
  });

  it("an ordinary denial that merely mentions approval stays 'Not permitted'", async () => {
    const id = fake.seed({ id: "inv-2", messages: messages("You do not have access. Approval is required from your account owner."), turns: [turn({})] as never });
    const conv = await open(id);
    expect(within(conv).getByText("Not permitted")).toBeInTheDocument();
    expect(within(conv).queryByText("Needs an approved plan")).toBeNull();
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "DENIED");
  });
});
