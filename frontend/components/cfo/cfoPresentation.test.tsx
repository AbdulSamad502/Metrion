import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CfoMetricResultRow, MARKETPLACE_OPTIONS, presetPeriods } from "@/components/cfo/primitives";
import { FinancialHealthSection } from "@/components/cfo/sections/ImportAndGoalSections";
import { ReconcileSection } from "@/components/cfo/sections/ReportingSections";
import { ToastProvider } from "@/components/ui/Toast";
import type { MetricResult } from "@/lib/api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const token = async () => "t";
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });

describe("reporting-period shortcuts", () => {
  it("work out calendar dates only, in the YYYY-MM-DD form the date fields hold", () => {
    const p = presetPeriods(new Date(2026, 9, 24)); // 24 Oct 2026, the seller's local day
    expect(p.map((x) => [x.label, x.start, x.end])).toEqual([
      ["This month", "2026-10-01", "2026-10-24"],
      ["Last month", "2026-09-01", "2026-09-30"],
      ["Last 30 days", "2026-09-25", "2026-10-24"],
    ]);
  });

  it("cross a year boundary and a short month correctly", () => {
    expect(presetPeriods(new Date(2027, 0, 15))[1]).toMatchObject({ start: "2026-12-01", end: "2026-12-31" });
    expect(presetPeriods(new Date(2026, 2, 31))[1]).toMatchObject({ start: "2026-02-01", end: "2026-02-28" });
  });

  it("fill the period start and end fields, leave the as-of date alone, and send nothing", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 24, 12));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<FinancialHealthSection getToken={token} />);
    await userEvent.setup({ advanceTimers: () => undefined }).click(screen.getByRole("button", { name: "Last month" }));
    expect(screen.getByLabelText("Period start")).toHaveValue("2026-09-01");
    expect(screen.getByLabelText("Period end")).toHaveValue("2026-09-30");
    expect(screen.getByLabelText("As-of date")).toHaveValue("");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("marketplace choice", () => {
  it("offers exactly the three supported marketplaces, with the same upper-case ids the backend already took", () => {
    expect(MARKETPLACE_OPTIONS.map((o) => o.value)).toEqual(["AMAZON", "FLIPKART", "MEESHO"]);
    render(<ReconcileSection getToken={token} />);
    const select = screen.getByLabelText("Marketplace") as HTMLSelectElement;
    expect(within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value)).toEqual(["", "AMAZON", "FLIPKART", "MEESHO"]);
    expect(select.value).toBe(""); // nothing is chosen for the seller
  });
});

describe("financial health result", () => {
  const run = async (body: unknown) => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(body)));
    render(<FinancialHealthSection getToken={token} />);
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("Period start"), "2026-09-01");
    await u.type(screen.getByLabelText("Period end"), "2026-09-30");
    await u.type(screen.getByLabelText("As-of date"), "2026-09-30");
    await u.click(screen.getByRole("button", { name: "Compute" }));
    return screen.findByTestId("health-bands-result");
  };

  it("shows each band in words, with the measure's name, and no raw JSON", async () => {
    const box = await run({ overallBand: "WATCH", perMetricBands: { CONTRIBUTION_MARGIN_PCT: "GOOD", FEE_RATIO_PCT: "AT_RISK", RETURN_RATE_PCT: "WATCH" }, engineResultRefs: [], unavailableReason: null });
    expect(box).toHaveTextContent("Overall");
    expect(box).toHaveTextContent("Watch");
    const rows = within(box).getAllByRole("listitem").map((r) => r.textContent);
    expect(rows).toEqual(["Contribution marginGood", "Fee ratioAt risk", "Return rateWatch"]);
    expect(box.textContent).not.toMatch(/[{}"]|_PCT|AT_RISK/);
  });

  it("says 'Not available' with the backend's own reason, never a made-up band", async () => {
    const box = await run({ overallBand: null, perMetricBands: {}, engineResultRefs: [], unavailableReason: "No profit and loss has been computed for this period." });
    expect(box).toHaveTextContent("Not available");
    expect(box).toHaveTextContent("No profit and loss has been computed for this period.");
    expect(within(box).queryByText(/Good|Watch|At risk/)).toBeNull();
  });

  it("shows a band name it does not know exactly as the backend sent it", async () => {
    const box = await run({ overallBand: "WATCH", perMetricBands: { NEW_METRIC: "STRETCHED" }, engineResultRefs: [], unavailableReason: null });
    expect(box).toHaveTextContent("NEW_METRIC");
    expect(box).toHaveTextContent("STRETCHED");
  });
});

describe("Copy ID on a result", () => {
  const result = { metricCode: "CONTRIBUTION_PROFIT", isAvailable: true, valuePaise: 12050, valueFraction: null, unavailableReason: null, confidence: "CONFIRMED", calculationBasis: "X", engineResultRef: "7c1d3e50-0000-4000-8000-000000000001" } as unknown as MetricResult;
  const show = () => render(<ToastProvider><CfoMetricResultRow label="Contribution profit" result={result} /></ToastProvider>);

  it("copies the whole reference and says so only after the browser accepted it", async () => {
    const u = userEvent.setup(); // set up first: user-event installs its own clipboard, which the stub below replaces
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    show();
    expect(screen.queryByText("ID copied.")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Copy ID" }));
    expect(writeText).toHaveBeenCalledWith("7c1d3e50-0000-4000-8000-000000000001");
    expect(await screen.findByText("ID copied.")).toBeInTheDocument();
  });

  it("says it could not copy, and never claims success, when the browser refuses", async () => {
    const u = userEvent.setup();
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => { throw new Error("denied"); }) } });
    show();
    await u.click(screen.getByRole("button", { name: "Copy ID" }));
    await waitFor(() => expect(screen.getByText(/Could not copy the ID/)).toBeInTheDocument());
    expect(screen.queryByText("ID copied.")).toBeNull();
  });
});
