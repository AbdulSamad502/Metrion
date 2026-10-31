import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CorrectionsPanel } from "@/components/cmo/performance/CorrectionsPanel";
import { VersionPanel } from "@/components/cmo/performance/VersionPanel";
import { ApiError } from "@/lib/api";
import type { LinesPage, MetricVals, PerfLine, PerformanceApi, VersionAnalysis } from "@/lib/cmoPerformance";

// Written with the corrections and version-pagination work; see the docs for whether this file has been run.
const vals = (over: Partial<MetricVals> = {}): MetricVals => ({ impressions: 100, clicks: 10, orders: 2, units: null, sales: 50000, ...over });
const line = (over: Partial<PerfLine> = {}): PerfLine => ({ lineId: "l1", importId: "i1", marketplace: "AMAZON", reportSku: "AQ-1", date: "2026-10-30", original: vals(), effective: vals(), corrected: false, correctionId: null, voided: false, sourceName: "oct.csv", importedAt: "2026-10-31T00:00:00Z", ...over });
const page = (lines: PerfLine[], over: Partial<LinesPage> = {}): LinesPage => ({ marketplace: "AMAZON", reportSku: null, start: "2026-10-02", end: "2026-10-31", total: lines.length, limit: 25, offset: 0, hasMore: false, lines, note: "A blank value means the report did not carry it.", aiCredits: 0, ...over });
const fake = (over: Partial<Record<keyof PerformanceApi, unknown>> = {}): PerformanceApi => ({
  lines: vi.fn(async () => page([line()])), correctionHistory: vi.fn(async () => ({ corrections: [], limit: 25, offset: 0, hasMore: false, aiCredits: 0 as const, note: "" })),
  correct: vi.fn(async () => ({ corrected: true as const, correctionId: "c1", at: "x", lineId: "l1", voided: false, changed: ["clicks"], previous: vals(), now: vals({ clicks: 20 }), original: vals(), message: "Saved. The imported value is kept.", aiCredits: 0 as const })), ...over,
}) as unknown as PerformanceApi;

describe("correcting an imported record", () => {
  it("shows the imported value, a blank as not reported, and nothing is saved until Save", async () => {
    const api = fake();
    render(<CorrectionsPanel api={api} version={0} onChanged={vi.fn()} />);
    const row = await screen.findByTestId("perf-line");
    expect(row).toHaveAttribute("data-corrected", "no");
    expect(row).toHaveTextContent("Units sold not reported");
    await userEvent.click(within(row).getByRole("button", { name: "Correct this record" }));
    const save = screen.getByRole("button", { name: "Save correction" });
    expect(save).toBeDisabled();
    expect(api.correct).not.toHaveBeenCalled();
  });

  it("sends only the changed value, the reason, and the correction it saw, then shows the saved message", async () => {
    const api = fake();
    const onChanged = vi.fn();
    render(<CorrectionsPanel api={api} version={0} onChanged={onChanged} />);
    await userEvent.click(await screen.findByRole("button", { name: "Correct this record" }));
    const clicks = screen.getByLabelText("Clicks");
    await userEvent.clear(clicks);
    await userEvent.type(clicks, "20");
    await userEvent.type(screen.getByLabelText("Reason"), "Typo in the report");
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(api.correct).toHaveBeenCalledWith({ lineId: "l1", changes: { clicks: "20" }, void: false, reason: "Typo in the report", expectedCorrectionId: null }));
    expect(await screen.findByTestId("correction-saved")).toHaveTextContent("The imported value is kept");
    expect(onChanged).toHaveBeenCalled();
  });

  it("a blank entry is sent as blank (not reported), never as zero, and a void sends no values", async () => {
    const api = fake();
    render(<CorrectionsPanel api={api} version={0} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Correct this record" }));
    await userEvent.clear(screen.getByLabelText("Orders"));
    await userEvent.type(screen.getByLabelText("Reason"), "Not in the report");
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(api.correct).toHaveBeenLastCalledWith(expect.objectContaining({ changes: { orders: null }, void: false })));
    await userEvent.click(await screen.findByRole("button", { name: "Correct this record" }));
    await userEvent.click(screen.getByLabelText(/wrong as a whole/));
    await userEvent.type(screen.getByLabelText("Reason"), "Whole row is wrong");
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(api.correct).toHaveBeenLastCalledWith(expect.objectContaining({ changes: {}, void: true })));
  });

  it("shows the original beside the corrected value and sends the current correction id when correcting again", async () => {
    const api = fake({ lines: vi.fn(async () => page([line({ corrected: true, correctionId: "c9", effective: vals({ clicks: 20 }) })])) });
    render(<CorrectionsPanel api={api} version={0} onChanged={vi.fn()} />);
    const row = await screen.findByTestId("perf-line");
    expect(row).toHaveAttribute("data-corrected", "yes");
    expect(within(row).getByTestId("corrected-badge")).toHaveTextContent("CORRECTED");
    expect(row).toHaveTextContent("Imported: Impressions 100 · Clicks 10");
    expect(row).toHaveTextContent("Used in your numbers: Impressions 100 · Clicks 20");
    await userEvent.click(within(row).getByRole("button", { name: "Correct again" }));
    await userEvent.type(screen.getByLabelText("Reason"), "Second fix");
    await userEvent.clear(screen.getByLabelText("Orders"));
    await userEvent.type(screen.getByLabelText("Orders"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(api.correct).toHaveBeenCalledWith(expect.objectContaining({ expectedCorrectionId: "c9" })));
  });

  it("shows a refusal (a stale correction) in plain words and keeps the form open", async () => {
    const api = fake({ correct: vi.fn(async () => { throw new ApiError(409, { code: "STALE", detail: "This record was corrected after you opened it." }); }) });
    render(<CorrectionsPanel api={api} version={0} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Correct this record" }));
    await userEvent.type(screen.getByLabelText("Clicks"), "1");
    await userEvent.type(screen.getByLabelText("Reason"), "Because");
    await userEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("corrected after you opened it");
    expect(screen.getByTestId("correction-form")).toBeInTheDocument();
  });

  it("lists past corrections with before, after and reason, and pages through the records", async () => {
    const hist = { corrections: [{ id: "c1", lineId: "l1", importId: "i1", sourceName: "oct.csv", marketplace: "AMAZON", reportSku: "AQ-1", date: "2026-10-30", previous: vals(), corrected: vals({ clicks: 20 }), voided: false, changed: ["clicks"], reason: "Typo", supersedes: null, by: "u", at: "2026-11-01T10:00:00Z" }], limit: 25, offset: 0, hasMore: false, aiCredits: 0 as const, note: "" };
    const lines = vi.fn(async (f: { offset?: number }) => page([line({ lineId: `l${f.offset ?? 0}` })], { total: 40, hasMore: (f.offset ?? 0) === 0, offset: f.offset ?? 0 }));
    const api = fake({ correctionHistory: vi.fn(async () => hist), lines });
    render(<CorrectionsPanel api={api} version={0} onChanged={vi.fn()} />);
    expect(await screen.findByTestId("correction-row")).toHaveTextContent("Reason: Typo");
    await userEvent.click(screen.getByRole("button", { name: "Older →" }));
    await waitFor(() => expect(lines).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 25 })));
  });
});

describe("version pagination", () => {
  const maps = { items: [{ sku: "aqua", product: "AquaNest", marketplace: "AMAZON", reportSku: "AQ-1", linkConfirmedAt: "x", status: "COMPLETE", missing: [], versions: [], history: { links: [], golives: [] } }], windowDays: 7, windowSetBy: "YOU", windowBounds: [7, 90], missing: [], hasImports: true, aiCredits: 0 };
  const ver = (n: number) => ({ versionId: `v${n}`, number: n, createdAt: "2026-10-01", source: "s", changedSection: null, wentLiveOn: null, state: "NOT_ASSESSED", needs: [], reasons: [] });
  const analysis = (from: number, to: number, over: Partial<VersionAnalysis> = {}): VersionAnalysis => ({ sku: "aqua", marketplace: "AMAZON", product: "AquaNest", source: "x", windowDays: 7, windowSetBy: "YOU", linked: "AQ-1",
    versions: Array.from({ length: to - from + 1 }, (_, i) => ver(from + i)) as never, needs: [], aiCredits: 0, total: 40, ...over }) as VersionAnalysis;

  it("loads a page, shows how many of the total, and loads the next page on request", async () => {
    const versions = vi.fn(async (_s: string, _m: string, p?: { offset?: number }) => ((p?.offset ?? 0) === 0 ? analysis(1, 25, { hasMore: true, offset: 0 }) : analysis(26, 40, { hasMore: false, offset: 25 })));
    render(<VersionPanel api={{ mappings: vi.fn(async () => maps), versions } as unknown as PerformanceApi} version={0} />);
    expect(await screen.findByTestId("version-count")).toHaveTextContent("Showing 25 of 40 versions");
    await userEvent.click(screen.getByTestId("load-more-versions"));
    await waitFor(() => expect(screen.getByTestId("version-count")).toHaveTextContent("Showing 40 of 40 versions"));
    expect(versions).toHaveBeenLastCalledWith("aqua", "AMAZON", { limit: 25, offset: 25, order: "asc" });
    expect(screen.queryByTestId("load-more-versions")).not.toBeInTheDocument();
  });

  it("can show the newest versions first", async () => {
    const versions = vi.fn(async () => analysis(1, 25, { hasMore: true }));
    render(<VersionPanel api={{ mappings: vi.fn(async () => maps), versions } as unknown as PerformanceApi} version={0} />);
    await screen.findByTestId("version-count");
    await userEvent.click(screen.getByLabelText("Newest first"));
    await waitFor(() => expect(versions).toHaveBeenLastCalledWith("aqua", "AMAZON", { limit: 25, order: "desc" }));
  });
});
