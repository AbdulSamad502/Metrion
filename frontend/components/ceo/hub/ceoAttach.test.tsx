import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// Spec 6.34: attachments. Files are uploaded first, then sent with the message by id; a refused file stops everything with a plain reason.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const pdf = (name = "statement.pdf") => new File(["%PDF-1.4"], name, { type: "application/pdf" });

async function openConversation() {
  const id = fake.seed({ id: "inv-1" });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
  await user().click(await screen.findByTestId("open-drawer"));
  await user().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
  return id;
}

describe("attachments", () => {
  it("shows the chosen files as chips, lets one be removed, uploads each, then sends the question with the file ids", async () => {
    const id = await openConversation();
    const u = user();
    await u.upload(screen.getByTestId("file-input"), [pdf("a.pdf"), pdf("b.pdf")]);
    expect(screen.getByTestId("attached-files")).toHaveTextContent("a.pdf");
    await u.click(screen.getByRole("button", { name: "Remove b.pdf" }));
    expect(screen.getByTestId("attached-files")).not.toHaveTextContent("b.pdf");
    await u.type(screen.getByLabelText("Ask the CEO"), "What does this PDF say?");
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByTestId("processing");
    expect(fake.calls.filter((c) => c.method === "uploadAttachment").map((c) => c.args)).toEqual([[id, "a.pdf"]]);
    const args = fake.calls.find((c) => c.method === "postTurn")!.args as unknown[];
    expect(args[1]).toBe("What does this PDF say?");
    expect(args[5]).toEqual([fake.uploads[0].id]);
    expect(screen.queryByTestId("attached-files")).not.toBeInTheDocument(); // cleared once sent
    fake.completeTurn({ answer: "ok" });
  });

  it("a file alone can be sent (the seller does not have to type), and the message says so plainly", async () => {
    await openConversation();
    const u = user();
    await u.upload(screen.getByTestId("file-input"), pdf());
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByTestId("processing");
    expect((fake.calls.find((c) => c.method === "postTurn")!.args as unknown[])[1]).toBe("Please read what I attached.");
    fake.completeTurn({ answer: "ok" });
  });

  it.each([
    ["ATTACHMENTS_NOT_CONFIGURED", /not set up yet by your operator/],
    ["ATTACHMENT_TYPE_NOT_SUPPORTED", /not a supported file/],
    ["ATTACHMENT_TOO_LARGE", /too large/],
  ])("a refused file (%s) is explained and nothing is sent", async (code, text) => {
    await openConversation();
    fake.uploadFails = new ApiError(code === "ATTACHMENTS_NOT_CONFIGURED" ? 503 : 415, { code });
    const u = user();
    await u.upload(screen.getByTestId("file-input"), pdf("x.pdf"));
    await u.type(screen.getByLabelText("Ask the CEO"), "hello");
    await u.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(fake.count("postTurn")).toBe(0);
  });

  it("with no conversation open, attaching and sending starts one first (the file needs somewhere to live)", async () => {
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const u = user();
    await u.upload(await screen.findByTestId("file-input"), pdf());
    await u.type(screen.getByLabelText("Ask the CEO"), "What is in this?");
    await u.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(fake.count("createInvestigation")).toBe(1));
    await screen.findByTestId("processing");
    expect(fake.count("uploadAttachment")).toBe(1);
    fake.completeTurn({ answer: "ok" });
  });
});
