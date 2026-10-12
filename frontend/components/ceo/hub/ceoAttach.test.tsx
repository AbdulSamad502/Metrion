import { render, screen, waitFor, within } from "@testing-library/react";
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
    ["ATTACHMENTS_NOT_CONFIGURED", /not switched on for this server.*CEO_ATTACHMENT_MAX_BYTES/],
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

describe("an attached image and competitor research", () => {
  const png = () => new File(["x"], "listing.png", { type: "image/png" });

  it("says plainly that chat does not read the image, and points to the Competitors page, without uploading or starting anything", async () => {
    await openConversation();
    const u = user();
    await u.upload(screen.getByTestId("file-input"), png());
    const hint = await screen.findByTestId("image-handoff");
    expect(hint).toHaveTextContent("does not read it or start any research");
    expect(within(hint).getByRole("link", { name: "Competitors page" })).toHaveAttribute("href", "/dashboard/competitors");
    expect(fake.uploads).toHaveLength(0); // choosing a file uploads nothing; the hint starts nothing
    expect(fake.count("postTurn")).toBe(0);
  });

  it("is not shown for a file that is not an image", async () => {
    await openConversation();
    await user().upload(screen.getByTestId("file-input"), pdf());
    expect(await screen.findByText("statement.pdf")).toBeInTheDocument();
    expect(screen.queryByTestId("image-handoff")).not.toBeInTheDocument();
  });

  it("goes away when the image is removed", async () => {
    await openConversation();
    const u = user();
    await u.upload(screen.getByTestId("file-input"), png());
    expect(await screen.findByTestId("image-handoff")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Remove listing.png" }));
    expect(screen.queryByTestId("image-handoff")).not.toBeInTheDocument();
  });
});

describe("the upload experience", () => {
  it("shows each file's size, and choosing the same file twice keeps one", async () => {
    await openConversation();
    const u = user();
    const f = new File([new Uint8Array(2048)], "orders.csv", { type: "text/csv", lastModified: 1 });
    await u.upload(screen.getByTestId("file-input"), f);
    await u.upload(screen.getByTestId("file-input"), f);
    const chips = await screen.findAllByTestId("attached-file");
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent("2 KB");
  });

  it("a spreadsheet says the CEO can read it in this conversation, and points to Profit & Finance for persistent records", async () => {
    await openConversation();
    await user().upload(screen.getByTestId("file-input"), new File(["a,b\n1,2"], "settlement.csv", { type: "text/csv" }));
    const note = await screen.findByTestId("report-handoff");
    expect(note).toHaveTextContent("Your CEO can read attached spreadsheets and analyze their contents in this conversation. For persistent financial records and formal marketplace reconciliation, use Profit & Finance.");
    expect(within(note).getByRole("link", { name: /Profit/ })).toHaveAttribute("href", "/dashboard/cfo");
  });

  it("a failed upload keeps the message and the file, marks it 'Not attached', and sends nothing", async () => {
    await openConversation();
    fake.uploadFails = new ApiError(500, { detail: "boom" });
    const u = user();
    await u.upload(screen.getByTestId("file-input"), pdf("x.pdf"));
    await u.type(screen.getByLabelText("Ask the CEO"), "please read");
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    expect(screen.getByTestId("attached-file")).toHaveAttribute("data-status", "failed");
    expect(screen.getByTestId("attached-file")).toHaveTextContent("Not attached");
    expect(screen.getByLabelText("Ask the CEO")).toHaveValue("please read");
    expect(fake.count("postTurn")).toBe(0);
  });

  it("a retry after a failure stores each file once and sends once", async () => {
    await openConversation();
    fake.uploadFails = new ApiError(500, { detail: "boom" });
    const u = user();
    const ok = pdf("ok.pdf");
    const bad = new File(["%PDF-1.4"], "bad.pdf", { type: "application/pdf", lastModified: 5 });
    await u.upload(screen.getByTestId("file-input"), ok);
    await u.type(screen.getByLabelText("Ask the CEO"), "go");
    await u.click(screen.getByRole("button", { name: "Send" })); // the first file fails
    await screen.findByRole("alert");
    fake.uploadFails = null;
    await u.upload(screen.getByTestId("file-input"), bad);
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByTestId("processing");
    expect(fake.count("uploadAttachment")).toBe(3); // ok.pdf failed once, then ok.pdf and bad.pdf succeeded
    expect(fake.uploads).toHaveLength(2); // each file is stored exactly once
    expect(fake.count("postTurn")).toBe(1);
    fake.completeTurn({ answer: "ok" });
  });
});

describe("what the backend read from a spreadsheet", () => {
  const sheet = (name = "report.xlsx") => new File(["a,b\n1,2"], name, { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", lastModified: 9 });

  it("shows the sheet names and the rows that were actually read once the file is uploaded, and nothing before", async () => {
    await openConversation();
    fake.uploadTable = { status: "READ", sheets: [{ name: "Orders", rows: 12, columns: 4, headerRow: 1, truncated: false }, { name: "Returns", rows: 3, columns: 4, headerRow: 1, truncated: false }], sheetsTruncated: false };
    fake.uploadFailsFor = "second.xlsx"; // the first file uploads, the second fails, so the composer keeps both and the first chip shows what was read
    const u = user();
    await u.upload(screen.getByTestId("file-input"), [sheet("first.xlsx"), sheet("second.xlsx")]);
    expect(screen.queryByTestId("file-info")).not.toBeInTheDocument(); // chosen, not uploaded: nothing is claimed as read
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    const chips = screen.getAllByTestId("attached-file");
    expect(within(chips[0]).getByTestId("file-info")).toHaveTextContent("Orders, Returns · 15 rows read");
    expect(chips[0]).toHaveAttribute("data-status", "uploaded");
    expect(chips[1]).toHaveAttribute("data-status", "failed");
    expect(within(chips[1]).queryByTestId("file-info")).not.toBeInTheDocument();
  });

  it("says when a spreadsheet could not be read as a table, and when a limit cut rows off", async () => {
    await openConversation();
    const u = user();
    fake.uploadTable = { status: "UNREADABLE", note: "That workbook could not be opened." };
    fake.uploadFailsFor = "other.xlsx";
    await u.upload(screen.getByTestId("file-input"), [sheet("bad.xlsx"), sheet("other.xlsx")]);
    await u.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    expect(within(screen.getAllByTestId("attached-file")[0]).getByTestId("file-info")).toHaveTextContent("Could not be read as a table: That workbook could not be opened.");
  });

  it("a limit that cut rows off is stated on the chip", async () => {
    await openConversation();
    fake.uploadTable = { status: "READ", sheets: [{ name: "(CSV)", rows: 50000, columns: 3, headerRow: 1, truncated: true }], sheetsTruncated: false };
    fake.uploadFailsFor = "b.csv";
    await user().upload(screen.getByTestId("file-input"), [new File(["x"], "a.csv", { type: "text/csv", lastModified: 1 }), new File(["x"], "b.csv", { type: "text/csv", lastModified: 2 })]);
    await user().click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("alert");
    expect(within(screen.getAllByTestId("attached-file")[0]).getByTestId("file-info")).toHaveTextContent("limit reached: not all rows were read");
  });
});
