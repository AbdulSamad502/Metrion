import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobProgress } from "@/components/cfo/v2/data/JobProgress";
import { UploadPanel } from "@/components/cfo/v2/data/UploadPanel";
import { marketplaceFor, pollDelayMs, type JobStatus, type JobView } from "@/lib/cfoV2/ingest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "tok" }) }));

const job = (over: Partial<JobView> = {}): JobView => ({
  jobId: "11111111-1111-4111-8111-111111111111",
  reportFileId: "22222222-2222-4222-8222-222222222222",
  status: "PARSING",
  reportKind: "SETTLEMENT",
  adapterId: null,
  mappingId: null,
  progressRows: 0,
  totalRowsEstimate: null,
  errorCode: null,
  errorDetail: null,
  outcome: null,
  attempt: 1,
  createdAt: null,
  startedAt: null,
  finishedAt: null,
  heartbeatAt: null,
  ...over,
});

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("poll cadence", () => {
  it("is 1 s while moving and backs off to 5 s", () => {
    expect([pollDelayMs(0), pollDelayMs(5), pollDelayMs(15)]).toEqual([1000, 2500, 5000]);
  });
  it("an expense file always belongs to the business", () => {
    expect(marketplaceFor("EXPENSE", "MEESHO")).toBe("ALL");
    expect(marketplaceFor("SALES", "MEESHO")).toBe("MEESHO");
  });
});

describe("JobProgress follows a job to its end", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows live progress, never moves backwards, then the quality report when done", async () => {
    const seq: JobView[] = [
      job({ progressRows: 500, totalRowsEstimate: 1000 }),
      job({ progressRows: 300, totalRowsEstimate: 1000 }), // a stale, out-of-order response
      job({
        status: "DONE",
        progressRows: 1000,
        totalRowsEstimate: 1000,
        qualityReport: { rows: { read: 1000, posted: 990, held_total: 4 }, needs_seller: ["4 row(s) were held"], confidence: "PROVISIONAL" },
      }),
    ];
    let i = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => (url.includes("/held") ? reply({ items: [], page: 1, pageSize: 20, total: 0, pageCount: 1, unresolved: 0 }) : url.includes("/access") ? reply({ canAdjust: false }) : reply(seq[Math.min(i++, seq.length - 1)]))));
    render(<JobProgress jobId={seq[0].jobId} />);
    expect(await screen.findByText(/500 rows read/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Rows read" })).toHaveAttribute("value", "500");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(screen.getByText(/500 rows read/)).toBeInTheDocument(); // 300 was ignored
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });
    expect(await screen.findByText("Finished · 1000 rows read")).toBeInTheDocument();
    expect(screen.getByText("Rows saved")).toBeInTheDocument();
    expect(screen.getByText("4 row(s) were held")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel upload" })).toBeNull(); // finished: nothing to cancel
  });

  it("a failed job shows the plain reason and offers another upload", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(job({ status: "FAILED", errorDetail: "The file has no header row." }))));
    const onRetry = vi.fn();
    render(<JobProgress jobId={job().jobId} onRetry={onRetry} />);
    expect(await screen.findByText("The file has no header row.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("cancel posts to the job and reloads", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url.replace(/^.*\/api\/v1/, "")}`);
        return reply(job({ status: calls.some((c) => c.startsWith("POST")) ? "CANCELLED" : "PARSING" }));
      }),
    );
    render(<JobProgress jobId={job().jobId} />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel upload" }));
    expect(calls.some((c) => c === `POST /cfo/jobs/${job().jobId}/cancel`)).toBe(true);
    expect(await screen.findByText(/Nothing from this file was saved/)).toBeInTheDocument();
  });

  it("a job waiting on the columns says nothing is saved until the seller confirms, and offers the review", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(job({ status: "AWAITING_MAPPING_CONFIRMATION" }))));
    const onConfirm = vi.fn();
    render(<JobProgress jobId={job().jobId} onConfirmMapping={onConfirm} />);
    expect(await screen.findByText(/Nothing is saved until you confirm it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review the columns" }));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("a poll that fails shows the reason and does not look like a failed upload", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ detail: "job not found" }, 404)));
    render(<JobProgress jobId={job().jobId} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Could not be read")).toBeNull();
  });

  const everyStatus: JobStatus[] = ["QUEUED", "PROFILING", "PARSING", "VALIDATING", "COMMITTING"];
  for (const s of everyStatus) {
    it(`${s} is active: cancellable`, async () => {
      vi.stubGlobal("fetch", vi.fn(() => reply(job({ status: s }))));
      render(<JobProgress jobId={job().jobId} />);
      expect(await screen.findByRole("button", { name: "Cancel upload" })).toBeInTheDocument();
    });
  }
});

describe("UploadPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uploads with the chosen kind and marketplace and hands the job on", async () => {
    let seen = "";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        seen = url;
        return reply(job({ status: "QUEUED" }), 202);
      }),
    );
    const onStarted = vi.fn();
    render(<UploadPanel onStarted={onStarted} />);
    await userEvent.selectOptions(screen.getByLabelText("What is this file?"), "ADVERTISING");
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "FLIPKART");
    await userEvent.upload(screen.getByLabelText(/File/), new File(["a,b\n1,2"], "ads.csv", { type: "text/csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(seen).toContain("/api/v1/cfo/uploads?marketplace=FLIPKART&report_kind=ADVERTISING");
    expect(onStarted).toHaveBeenCalledWith(expect.objectContaining({ status: "QUEUED" }));
  });

  it("an expense file hides the marketplace and is sent as ALL", async () => {
    let seen = "";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        seen = url;
        return reply(job({ status: "QUEUED", reportKind: "EXPENSE" }), 202);
      }),
    );
    render(<UploadPanel onStarted={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText("What is this file?"), "EXPENSE");
    expect(screen.queryByLabelText("Marketplace")).toBeNull();
    await userEvent.upload(screen.getByLabelText(/File/), new File(["x"], "exp.csv", { type: "text/csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(seen).toContain("marketplace=ALL&report_kind=EXPENSE");
  });

  it("a refusal (no permission, wrong file) is shown in plain words and nothing is started", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ detail: "Please upload a .csv or .xlsx file." }, 400)));
    const onStarted = vi.fn();
    render(<UploadPanel onStarted={onStarted} />);
    await userEvent.upload(screen.getByLabelText(/File/), new File(["x"], "a.csv", { type: "text/csv" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/csv or .xlsx/);
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("Upload stays disabled until a file is chosen", () => {
    render(<UploadPanel onStarted={() => {}} />);
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });
});
