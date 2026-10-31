import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmationsPanel } from "@/components/cmo/performance/ConfirmationsPanel";
import { ImportPanel } from "@/components/cmo/performance/ImportPanel";
import { PerformanceDashboard } from "@/components/cmo/performance/PerformanceDashboard";
import { VersionPanel } from "@/components/cmo/performance/VersionPanel";
import { PerformanceCard } from "@/components/ceo/hub/PerformanceCard";
import { ApiError } from "@/lib/api";
import { cmoDraftFromParams, describeChange, formatMetric, handoffHref, isPerformanceCard, performanceError } from "@/lib/cmoPerformance";
import type { Comparison, Dashboard, ImportPreview, Mappings, Metric, MetricKey, PerformanceApi, PerformanceCard as Card, Summary, VersionAnalysis } from "@/lib/cmoPerformance";

const KEYS: MetricKey[] = ["impressions", "clicks", "ctr", "orders", "cvr", "units", "sales"];
const met = (value: number | null, state: Metric["state"] = "AVAILABLE", reason: string | null = null): Metric => ({ state, value, reason });
const summary = (over: Partial<Summary> = {}): Summary => ({
  periodStart: "2026-10-25", periodEnd: "2026-10-31", days: 7, coveredDays: 7, complete: true,
  metrics: { impressions: met(1400), clicks: met(70), ctr: met(500), orders: met(14), cvr: met(2000), units: met(null, "UNAVAILABLE", "Your reports do not carry units sold for this period."), sales: met(350000) }, ...over,
});
const comparison = (): Comparison => Object.fromEntries(KEYS.map((k) => [k, k === "units"
  ? { state: "NOT_ASSESSED", reason: "The later period: Your reports do not carry units sold for this period." }
  : { state: "AVAILABLE", previous: 700, current: 1400, difference: 700, relativeBp: 10000, direction: "UP" }])) as unknown as Comparison;
const dashboard = (over: Partial<Dashboard> = {}): Dashboard => ({
  filters: { marketplace: null, sku: null, start: "2026-10-25", end: "2026-10-31" }, aiCredits: 0, products: [{ sku: "aquanest", name: "AquaNest bottle", marketplaces: ["AMAZON"], linked: ["AMAZON"] }], marketplaces: ["AMAZON"],
  dataSpan: { lastImportAt: "2026-10-31T08:00:00Z", first: "2026-10-01", last: "2026-10-31" }, source: "your imported performance reports", current: summary(), previous: summary({ periodStart: "2026-10-18", periodEnd: "2026-10-24" }), comparison: comparison(),
  trend: [{ date: "2026-10-30", impressions: 100, clicks: 10, orders: 2, units: null, sales: 5000, ctr: 1000, cvr: 2000 }, { date: "2026-10-31", impressions: 300, clicks: 10, orders: null, units: null, sales: 5000, ctr: 333, cvr: null }],
  insights: [{ kind: "IMPRESSIONS_UP_CTR_DOWN", what: "Impressions were higher in 2026-10-25 to 2026-10-31 than in 2026-10-18 to 2026-10-24, but the click-through rate was lower.",
    evidence: [{ metric: "impressions", label: "Impressions", previous: "700", current: "1,400", previousPeriod: "2026-10-18 to 2026-10-24", currentPeriod: "2026-10-25 to 2026-10-31" }], whyItMatters: "More people saw it while a smaller share clicked.",
    nextStep: "Review the title for clarity.", action: { kind: "TITLE", route: "M3", label: "Review title clarity and keyword relevance", ask: "analyse my title options" }, limits: ["This compares two periods. It does not show that anything you changed caused the difference."], measured: true, explanation: "x" }],
  needs: [], limits: [], imports: [{ id: "i1", marketplace: "AMAZON", sourceName: "oct.csv", periodStart: "2026-10-01", periodEnd: "2026-10-31", rowsSaved: 31, rowsSkipped: 0, metrics: ["impressions"], importedAt: "2026-10-31T08:00:00Z" }],
  never: "This compares two periods. It does not show that anything you changed caused the difference.", ...over,
});
const mappings = (over: Partial<Mappings> = {}): Mappings => ({
  items: [{ sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", reportSku: null, linkConfirmedAt: null, status: "NEEDS_CONFIRMATION", missing: ["your confirmation of which SKU in your reports is this product", "a go-live date for version 1"],
    versions: [{ versionId: "v1", number: 1, createdAt: "2026-10-01", wentLiveOn: null, confirmedAt: null }], history: { links: [], golives: [] } }],
  windowDays: null, windowSetBy: null, windowBounds: [7, 90], missing: ["the comparison period length in days (set it on the performance page or tell me in chat)", "your confirmation of which SKU in your reports is this product", "a go-live date for version 1"], hasImports: true, aiCredits: 0, ...over,
});
const fake = (over: Partial<Record<keyof PerformanceApi, unknown>> = {}): PerformanceApi => ({
  dashboard: vi.fn(async () => dashboard()), mappings: vi.fn(async () => mappings()), versions: vi.fn(), candidates: vi.fn(async () => ({ candidates: [{ reportSku: "AQ-1", reportTitle: null, rows: 31, firstOrder: null, lastOrder: null }], note: "" })),
  previewImport: vi.fn(), importReport: vi.fn(), linkSku: vi.fn(async () => ({ linked: true as const, previous: null, message: "Saved as your statement." })),
  confirmGoLive: vi.fn(async () => ({ recorded: true as const, previous: null, message: "Saved as your statement. Metrion cannot see the marketplace." })), setWindow: vi.fn(async (days: number) => ({ days, message: `Saved. ${days}-day periods.` })), ...over,
}) as unknown as PerformanceApi;

describe("formatting (whole numbers only)", () => {
  it("formats counts, rupees in Indian grouping and rates in percent", () => {
    expect(formatMetric("orders", 1234567)).toBe("1,234,567");
    expect(formatMetric("sales", 12345678)).toBe("₹1,23,456.78");
    expect(formatMetric("sales", 5)).toBe("₹0.05");
    expect(formatMetric("ctr", 235)).toBe("2.35%");
    expect(formatMetric("cvr", 5)).toBe("0.05%");
  });
  it("describes a change in words and a mark, and says not assessed when it cannot", () => {
    expect(describeChange("orders", { state: "AVAILABLE", previous: 10, current: 15, difference: 5, relativeBp: 5000, direction: "UP" })).toBe("▲ Up 5 (+50.00%) from the previous period");
    expect(describeChange("ctr", { state: "AVAILABLE", previous: 1000, current: 500, difference: -500, relativeBp: null, direction: "DOWN" })).toBe("▼ Down 5.00 points from the previous period");
    expect(describeChange("orders", { state: "AVAILABLE", previous: 3, current: 3, difference: 0, relativeBp: 0, direction: "SAME" })).toContain("Same");
    expect(describeChange("units", { state: "NOT_ASSESSED", reason: "x" })).toBe("Not assessed");
  });
  it("turns a backend refusal into its plain sentence and code", () => {
    expect(performanceError(new ApiError(409, { code: "LINK_EXISTS", detail: "You already confirmed it." }))).toEqual({ message: "You already confirmed it.", code: "LINK_EXISTS" });
    expect(performanceError(new Error("boom")).message).toContain("Nothing was changed");
  });
});

describe("the dashboard", () => {
  it("shows each available figure with its source, period and coverage, and never shows zero for what is unavailable", async () => {
    render(<PerformanceDashboard api={fake()} />);
    expect(await screen.findByTestId("metric-orders")).toHaveTextContent("14");
    expect(screen.getByTestId("metric-sales")).toHaveTextContent("₹3,500.00");
    expect(screen.getByTestId("metric-ctr")).toHaveTextContent("5.00%");
    expect(screen.getByTestId("change-impressions")).toHaveTextContent("▲ Up 700 (+100.00%) from the previous period");
    const units = screen.getByTestId("metric-units");
    expect(units).toHaveAttribute("data-state", "UNAVAILABLE");
    expect(units).toHaveTextContent("UNAVAILABLE");
    expect(units).toHaveTextContent("Your reports do not carry units sold");
    expect(units).not.toHaveTextContent(/\b0\b/);
    expect(screen.getByTestId("data-coverage")).toHaveTextContent("your imported performance reports");
    expect(screen.getByTestId("data-coverage")).toHaveTextContent("7 of 7 days covered");
    expect(screen.getByTestId("data-coverage")).toHaveTextContent("Last import: 2026-10-31");
  });

  it("shows NOT ASSESSED with the reason for an incomplete period, and no value", async () => {
    const cur = summary({ coveredDays: 4, complete: false, metrics: { ...summary().metrics, orders: met(null, "NOT_ASSESSED", "Imported reports leave 3 of 7 days of this period uncovered, so a total would be misleading.") } });
    render(<PerformanceDashboard api={fake({ dashboard: vi.fn(async () => dashboard({ current: cur, limits: ["Imported reports cover 4 of 7 days of the chosen period."] })) })} />);
    const orders = await screen.findByTestId("metric-orders");
    expect(orders).toHaveAttribute("data-state", "NOT_ASSESSED");
    expect(orders).toHaveTextContent("NOT ASSESSED");
    expect(orders).toHaveTextContent("uncovered");
    expect(screen.getByTestId("data-coverage")).toHaveTextContent("4 of 7 days covered");
  });

  it("labels measured figures, possible reasons and limits, and never says a change caused a result", async () => {
    render(<PerformanceDashboard api={fake()} />);
    const i = await screen.findByTestId("insight");
    expect(within(i).getByText(/Measured:/)).toBeInTheDocument();
    expect(i).toHaveTextContent("Why it may matter (possible, not measured)");
    expect(i).toHaveTextContent("Next step:");
    expect(i).toHaveTextContent("Limit:");
    expect(i).toHaveTextContent("analyse my title options");
    expect(screen.getByTestId("insights").textContent).not.toMatch(/\bbecause of your\b|\bguarantee/i);
  });

  it("passes the chosen product, marketplace and dates to the backend, and refuses half a date range", async () => {
    const api = fake();
    render(<PerformanceDashboard api={api} />);
    await screen.findByTestId("metric-orders");
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "AMAZON");
    await userEvent.selectOptions(screen.getByLabelText("Product"), "aquanest");
    await userEvent.type(screen.getByLabelText("From date"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByText("Choose both dates, or neither.")).toBeInTheDocument();
    expect(api.dashboard).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByLabelText("To date"), "2026-10-31");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(api.dashboard).toHaveBeenLastCalledWith({ marketplace: "AMAZON", sku: "aquanest", start: "2026-10-01", end: "2026-10-31" }));
  });

  it("names what is missing for a product and shows an honest empty state with no import", async () => {
    const none = summary({ coveredDays: 0, complete: false, metrics: Object.fromEntries(KEYS.map((k) => [k, met(null, "UNAVAILABLE", "Your imported reports have no rows for this period.")])) as Summary["metrics"] });
    render(<PerformanceDashboard api={fake({ dashboard: vi.fn(async () => dashboard({ current: none, previous: none, needs: ["your confirmation of which SKU in your reports is this product"], trend: [], imports: [], insights: [] })) })} />);
    expect(await screen.findByTestId("needs")).toHaveTextContent("which SKU");
    expect(screen.getByTestId("trend-empty")).toBeInTheDocument();
    expect(screen.getByTestId("no-imports")).toHaveTextContent("nothing is estimated");
    for (const k of KEYS) expect(screen.getByTestId(`metric-${k}`)).toHaveAttribute("data-state", "UNAVAILABLE");
  });

  it("draws a trend with gaps for missing days and offers the same numbers as a table", async () => {
    render(<PerformanceDashboard api={fake()} />);
    await screen.findByTestId("metric-orders");
    expect(screen.getByTestId("trend-impressions")).toBeInTheDocument();
    expect(screen.getByTestId("trend-orders-none")).toHaveTextContent("not enough days");
    const table = screen.getByTestId("trend-table");
    expect(within(table).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("shows a plain error and keeps nothing invented when the data cannot be read", async () => {
    render(<PerformanceDashboard api={fake({ dashboard: vi.fn(async () => { throw new ApiError(422, { code: "BAD_RANGE", detail: "The end date is before the start date." }); }) })} />);
    expect(await screen.findByTestId("performance-error")).toHaveTextContent("The end date is before the start date.");
    expect(screen.queryByTestId("metric-orders")).toBeNull();
  });
});

const preview = (over: Partial<ImportPreview> = {}): ImportPreview => ({
  sha256: "a".repeat(64), fileName: "oct.csv", marketplace: "AMAZON", ok: true, errors: [], errorCount: 0, warnings: ["Not stored: CTR."], metrics: ["impressions", "clicks"], ignoredColumns: ["Notes"], rowCount: 2,
  period: { start: "2026-10-01", end: "2026-10-02", days: 2 }, newRows: 2, duplicateRows: 0, conflicts: [], sample: [{ date: "2026-10-01", sku: "AQ-1", impressions: "100", clicks: "—" }], alreadyImported: null, canImport: true, aiCredits: 0, ...over,
});
const csv = () => new File(["Date,SKU\n"], "oct.csv", { type: "text/csv" });

describe("importing a report", () => {
  it("previews first, shows period and a dash for a missing value, and imports only the previewed file", async () => {
    const api = fake({ previewImport: vi.fn(async () => preview()), importReport: vi.fn(async () => ({ imported: true, importId: "i", importedAt: "2026-10-31T00:00:00Z", marketplace: "AMAZON", rowsSaved: 2, rowsSkipped: 0, period: { start: "2026-10-01", end: "2026-10-02", days: 2 }, metrics: [], message: "Imported 2 row(s). Nothing was published or changed on a marketplace." })) });
    const onImported = vi.fn();
    render(<ImportPanel api={api} imports={[]} onImported={onImported} />);
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    await userEvent.upload(screen.getByLabelText("Report file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    const p = await screen.findByTestId("import-preview");
    expect(p).toHaveTextContent("Reporting period 2026-10-01 to 2026-10-02");
    expect(within(screen.getByTestId("import-sample")).getByText("—")).toBeInTheDocument();
    expect(api.importReport).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Import these rows" }));
    await waitFor(() => expect(api.importReport).toHaveBeenCalledWith(expect.any(File), "AMAZON", "a".repeat(64)));
    expect(await screen.findByTestId("import-message")).toHaveTextContent("Nothing was published");
    expect(onImported).toHaveBeenCalled();
  });

  it("lists every problem and cannot import an invalid file", async () => {
    const bad = preview({ ok: false, canImport: false, period: null, errorCount: 3, errors: [{ row: 2, message: "Row 2: the date “x” is not a valid date." }] });
    render(<ImportPanel api={fake({ previewImport: vi.fn(async () => bad) })} imports={[]} onImported={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("Report file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByTestId("import-errors")).toHaveTextContent("3 problems");
    expect(screen.getByTestId("import-errors")).toHaveTextContent("…and 2 more");
    expect(screen.getByRole("button", { name: "Import these rows" })).toBeDisabled();
  });

  it("refuses a duplicate file and rows that conflict with saved records", async () => {
    const dup = preview({ canImport: false, alreadyImported: { importedAt: "2026-10-20T00:00:00Z", fileName: "oct.csv", periodStart: "2026-10-01", periodEnd: "2026-10-02" }, conflictCount: 1, conflicts: [{ row: 2, message: "Row 2: AQ-1 on 2026-10-01 is already saved with different numbers. Existing records are never overwritten." }] });
    render(<ImportPanel api={fake({ previewImport: vi.fn(async () => dup) })} imports={[]} onImported={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("Report file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/already imported on 2026-10-20/)).toBeInTheDocument();
    expect(screen.getByTestId("import-conflicts")).toHaveTextContent("never overwritten");
    expect(screen.getByRole("button", { name: "Import these rows" })).toBeDisabled();
  });

  it("shows a plain message when the backend refuses the file", async () => {
    render(<ImportPanel api={fake({ previewImport: vi.fn(async () => { throw new ApiError(422, { code: "BAD_FILE", detail: "Only .csv and .xlsx files can be imported." }); }) })} imports={[]} onImported={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("Report file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByTestId("import-message")).toHaveTextContent("Only .csv and .xlsx files can be imported.");
  });
});

describe("the seller's confirmations", () => {
  it("lists what is missing and assumes no go-live date", async () => {
    render(<ConfirmationsPanel api={fake()} onChanged={vi.fn()} />);
    const list = await screen.findByTestId("missing-list");
    expect(list).toHaveTextContent("comparison period length");
    expect(list).toHaveTextContent("which SKU");
    const row = screen.getByTestId("golive-row");
    expect(row).toHaveTextContent("no go-live date confirmed");
    expect(row).toHaveTextContent("not assumed from when it was written, approved or copied");
  });

  it("connects a SKU chosen from the seller's own reports, and asks before replacing an earlier one", async () => {
    const linkSku = vi.fn()
      .mockRejectedValueOnce(new ApiError(409, { code: "LINK_EXISTS", detail: "You already confirmed that this product is “AQ-0”. Confirm the change explicitly to replace it." }))
      .mockResolvedValueOnce({ linked: true, previous: "AQ-0", message: "Saved as your statement." });
    const onChanged = vi.fn();
    render(<ConfirmationsPanel api={fake({ linkSku })} onChanged={onChanged} />);
    await screen.findByTestId("missing-list");
    await userEvent.click(screen.getByRole("button", { name: "Connect a SKU" }));
    await userEvent.selectOptions(await screen.findByLabelText("SKU for AquaNest bottle"), "AQ-1");
    await userEvent.click(within(screen.getByTestId("link-row")).getByRole("button", { name: "Save" }));
    expect(linkSku).toHaveBeenLastCalledWith({ sku: "aquanest", marketplace: "AMAZON", reportSku: "AQ-1", replace: false });
    const ask = await screen.findByTestId("replace-ask");
    expect(ask).toHaveTextContent("Confirm the change explicitly");
    expect(onChanged).not.toHaveBeenCalled();
    await userEvent.click(within(ask).getByRole("button", { name: "Replace it" }));
    await waitFor(() => expect(linkSku).toHaveBeenLastCalledWith({ sku: "aquanest", marketplace: "AMAZON", reportSku: "AQ-1", replace: true }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("confirms a go-live date only when the seller picks one, within the allowed range", async () => {
    const api = fake();
    render(<ConfirmationsPanel api={api} onChanged={vi.fn()} />);
    await screen.findByTestId("golive-row");
    const confirm = screen.getByRole("button", { name: "Confirm date" });
    expect(confirm).toBeDisabled();
    const date = screen.getByLabelText("Go-live date of version 1");
    expect(date).toHaveAttribute("min", "2026-10-01");
    await userEvent.type(date, "2026-10-03");
    await userEvent.click(confirm);
    await waitFor(() => expect(api.confirmGoLive).toHaveBeenCalledWith({ generationId: "v1", wentLiveOn: "2026-10-03", replace: false }));
    expect(await screen.findByText(/Metrion cannot see the marketplace/)).toBeInTheDocument();
  });

  it("validates the comparison period (7 to 90 whole days) before it can be saved", async () => {
    const api = fake();
    render(<ConfirmationsPanel api={api} onChanged={vi.fn()} />);
    await screen.findByTestId("window-box");
    const save = within(screen.getByTestId("window-box")).getByRole("button", { name: "Save" });
    const input = screen.getByLabelText("Comparison period in days");
    for (const bad of ["6", "91", "7.5", "-3"]) {
      await userEvent.clear(input);
      await userEvent.type(input, bad);
      expect(save).toBeDisabled();
    }
    await userEvent.clear(input);
    await userEvent.type(input, "14");
    expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(api.setWindow).toHaveBeenCalledWith(14));
  });

  it("says nothing is missing only when everything is confirmed", async () => {
    const done = mappings({ windowDays: 14, windowSetBy: "YOU", missing: [], items: [{ ...mappings().items[0], reportSku: "AQ-1", linkConfirmedAt: "2026-10-02T00:00:00Z", status: "COMPLETE", missing: [], versions: [{ versionId: "v1", number: 1, createdAt: "2026-10-01", wentLiveOn: "2026-10-03", confirmedAt: "2026-10-04T00:00:00Z" }] }] });
    render(<ConfirmationsPanel api={fake({ mappings: vi.fn(async () => done) })} onChanged={vi.fn()} />);
    expect(await screen.findByTestId("nothing-missing")).toBeInTheDocument();
    expect(screen.getByTestId("window-box")).toHaveTextContent("14 days before and 14 days after");
  });
});

const analysis = (over: Partial<VersionAnalysis> = {}): VersionAnalysis => ({
  sku: "aquanest", marketplace: "AMAZON", product: "AquaNest bottle", source: "your imported performance reports", windowDays: 7, windowSetBy: "YOU", linked: "AQ-1", needs: [], aiCredits: 0,
  versions: [
    { versionId: "v1", number: 1, createdAt: "2026-10-01", source: "Original listing written by Metrion", changedSection: null, wentLiveOn: "2026-10-03", state: "OBSERVED_COMPARABLE", needs: [], reasons: [], attribution: "NOT_ATTRIBUTED",
      previous: summary({ periodStart: "2026-09-26", periodEnd: "2026-10-02" }), following: summary({ periodStart: "2026-10-03", periodEnd: "2026-10-09" }), comparison: comparison(),
      observations: ["Impressions was higher in the 7 days after version 1 went live than in the 7 days before (700 → 1,400)."], insights: [], note: "This shows what was observed in each period. It does not show that the listing change caused it." },
    { versionId: "v2", number: 2, createdAt: "2026-10-05", source: "Your own edit", changedSection: "BULLET 2", wentLiveOn: null, state: "NOT_ASSESSED", needs: ["the date you put version 2 live (nothing is assumed from when it was created or approved)"], reasons: [] },
    { versionId: "v3", number: 3, createdAt: "2026-10-06", source: "Your own edit", changedSection: null, wentLiveOn: "2026-10-06", state: "INCOMPARABLE", needs: [], reasons: ["OVERLAPPING_PERIODS"], note: "Another version went live inside these periods, so the two periods are not a clean before and after." },
  ],
  ...over,
});

describe("before and after each version", () => {
  it("shows a compared version as observation only, and names what is needed for the others", async () => {
    render(<VersionPanel api={fake({ versions: vi.fn(async () => analysis()) })} version={0} />);
    const rows = await screen.findAllByTestId("version-row");
    expect(rows.map((r) => r.getAttribute("data-state"))).toEqual(["OBSERVED_COMPARABLE", "NOT_ASSESSED", "INCOMPARABLE"]);
    expect(within(rows[0]).getByTestId("version-table")).toHaveTextContent("Not assessed");
    expect(rows[0]).toHaveTextContent("It does not show that the listing change caused it");
    expect(rows[0]).not.toHaveTextContent(/caused an increase|improved/i);
    expect(rows[1]).toHaveTextContent("I need the date you put version 2 live");
    expect(rows[2]).toHaveTextContent("Another version went live inside these periods");
  });

  it("names what is needed when there is no SKU link or period length", async () => {
    render(<VersionPanel api={fake({ versions: vi.fn(async () => analysis({ windowDays: null, linked: null, needs: ["the comparison period length in days", "your confirmation of which SKU"], versions: [] })) })} version={0} />);
    expect(await screen.findByTestId("version-needs")).toHaveTextContent("I need your confirmation of which SKU");
  });
});

describe("the chat card", () => {
  const base = { kind: "LISTING_PERFORMANCE", page: "/dashboard/cmo/performance", aiCredits: 0 } as const;
  it("recognises its own cards only", () => {
    expect(isPerformanceCard({ ...base, view: "OVERVIEW" })).toBe(true);
    expect(isPerformanceCard({ kind: "LISTING_HISTORY", view: "HISTORY" })).toBe(false);
  });

  it("proposes a SKU link and saves only when Save is pressed, asking before it replaces", async () => {
    const linkSku = vi.fn().mockRejectedValueOnce(new ApiError(409, { code: "LINK_EXISTS", detail: "You already confirmed AQ-0." })).mockResolvedValueOnce({ linked: true, previous: "AQ-0", message: "Saved as your statement." });
    const card: Card = { ...base, view: "CONFIRM_LINK", product: "AquaNest bottle", proposal: { sku: "aquanest", marketplace: "AMAZON", reportSku: "AQ-1" }, replaces: null };
    render(<PerformanceCard card={card} api={fake({ linkSku })} onSend={vi.fn()} />);
    expect(linkSku).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You already confirmed AQ-0.");
    await userEvent.click(screen.getByRole("button", { name: "Replace it" }));
    await waitFor(() => expect(linkSku).toHaveBeenLastCalledWith({ sku: "aquanest", marketplace: "AMAZON", reportSku: "AQ-1", replace: true }));
    expect(await screen.findByText(/Saved as your statement/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("saves a go-live date and a comparison length through the same routes", async () => {
    const api = fake();
    const { unmount } = render(<PerformanceCard card={{ ...base, view: "CONFIRM_GOLIVE", product: "AquaNest bottle", proposal: { generationId: "v2", wentLiveOn: "2026-10-03", number: 2 } }} api={api} onSend={vi.fn()} />);
    expect(screen.getByText(/Metrion cannot verify this date/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.confirmGoLive).toHaveBeenCalledWith({ generationId: "v2", wentLiveOn: "2026-10-03", replace: false }));
    unmount();
    render(<PerformanceCard card={{ ...base, view: "CONFIRM_WINDOW", proposal: { days: 14 } }} api={api} onSend={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.setWindow).toHaveBeenCalledWith(14));
  });

  it("answers a question with one tap, without saving anything", async () => {
    const onSend = vi.fn();
    render(<PerformanceCard card={{ ...base, view: "CLARIFY", question: "Which product do you mean?", options: [{ label: "AquaNest bottle" }, { label: "NovaFlask" }] }} api={fake()} onSend={onSend} />);
    await userEvent.click(screen.getByRole("button", { name: "NovaFlask" }));
    expect(onSend).toHaveBeenCalledWith("NovaFlask");
  });

  it("shows the overview figures that exist and names the ones that do not", () => {
    const tiles = [{ key: "orders", label: "Orders", value: "14", change: "▲ Up 7 (+100.00%) from the previous period" }];
    render(<PerformanceCard card={{ ...base, view: "OVERVIEW", tiles, notShown: ["units sold"], period: { start: "2026-10-25", end: "2026-10-31", covered: 7, days: 7, source: "your imported performance reports" } }} api={fake()} onSend={vi.fn()} />);
    const card = screen.getByTestId("listing-performance");
    expect(card).toHaveTextContent("Orders");
    expect(card).toHaveTextContent("▲ Up 7 (+100.00%)");
    expect(card).toHaveTextContent("7 of 7 days covered");
    expect(card).toHaveTextContent("Not shown: units sold");
    expect(screen.getByRole("link", { name: /Open the performance page/ })).toHaveAttribute("href", "/dashboard/cmo/performance");
  });

  it("lists what is missing", () => {
    render(<PerformanceCard card={{ ...base, view: "MISSING", missing: ["a go-live date for version 2"] }} api={fake()} onSend={vi.fn()} />);
    expect(screen.getByLabelText("Still missing")).toHaveTextContent("a go-live date for version 2");
  });
});

describe("the one-click hand-off", () => {
  const action = (kind: "TITLE" | "CONTENT" | "KEYWORDS" | "REVISE") => ({ kind, route: "M3", label: "Review", ask: "x", draft: "d", product: "AquaNest bottle", marketplace: "AMAZON" });
  it("links to the hub with a kind, product and marketplace, and only when all are known", () => {
    expect(handoffHref(action("TITLE"))).toBe("/dashboard/ceo-hub?ask=cmo&kind=TITLE&about=AquaNest+bottle&mp=AMAZON");
    expect(handoffHref({ ...action("TITLE"), draft: null })).toBeNull();
    expect(handoffHref({ ...action("TITLE"), marketplace: undefined })).toBeNull();
  });
  it("turns a link back into the exact sentence the backend tests prove reaches the existing workflow, and nothing else", () => {
    expect(cmoDraftFromParams("cmo", "TITLE", "AquaNest bottle", "AMAZON")).toBe("What should I improve next in my AquaNest bottle listing on Amazon?");
    expect(cmoDraftFromParams("cmo", "KEYWORDS", "AquaNest bottle", "FLIPKART")).toBe("What should I improve next in my AquaNest bottle listing on Flipkart?");
    expect(cmoDraftFromParams("cmo", "CONTENT", "AquaNest bottle", "AMAZON")).toBe("What questions will buyers ask about my AquaNest bottle?");
    expect(cmoDraftFromParams("cmo", "REVISE", "AquaNest bottle", "MEESHO")).toBe("Show my latest AquaNest bottle listing on Meesho");
    for (const bad of [["research", "TITLE", "x", "AMAZON"], ["cmo", "DELETE", "x", "AMAZON"], ["cmo", "TITLE", "", "AMAZON"], ["cmo", "TITLE", "x", "EBAY"], ["cmo", "TITLE", "x".repeat(121), "AMAZON"], ["cmo", "TITLE", "x", null]] as (string | null)[][]) {
      expect(cmoDraftFromParams(bad[0], bad[1], bad[2], bad[3])).toBeNull();
    }
  });
  it("shows the link on an insight that has a hand-off, and the plain sentence otherwise", async () => {
    const d = dashboard();
    d.insights[0].action = action("TITLE");
    const { unmount } = render(<PerformanceDashboard api={fake({ dashboard: vi.fn(async () => d) })} />);
    expect(await screen.findByTestId("handoff")).toHaveAttribute("href", expect.stringContaining("ask=cmo&kind=TITLE"));
    expect(screen.getByTestId("handoff")).toHaveTextContent("you press send");
    unmount();
    d.insights[0].action = { ...action("TITLE"), draft: null };
    render(<PerformanceDashboard api={fake({ dashboard: vi.fn(async () => d) })} />);
    await screen.findByTestId("insight");
    expect(screen.queryByTestId("handoff")).toBeNull();
    expect(screen.getByTestId("insight")).toHaveTextContent("Ask me:");
  });
});
