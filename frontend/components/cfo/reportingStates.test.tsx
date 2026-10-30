import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CfoPreviewSection, ReconcileSection } from "@/components/cfo/sections/ReportingSections";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const token = async () => "t";
let next: () => Response;
beforeEach(() => vi.stubGlobal("fetch", vi.fn(async () => next())));
afterEach(() => vi.unstubAllGlobals());

async function run(ui: React.ReactElement, button: string) {
  render(ui);
  const user = userEvent.setup();
  await user.selectOptions(screen.getAllByLabelText("Marketplace")[0], "MEESHO");
  await user.type(screen.getByLabelText("Period start"), "2026-09-01");
  await user.type(screen.getByLabelText("Period end"), "2026-09-30");
  await user.type(screen.getByLabelText("As-of date"), "2026-09-30");
  await user.click(screen.getByRole("button", { name: button }));
}
const recon = (over: object) => ({ reconciliationRunId: "4e4c97ef-0000", findings: [], matchCount: 0, exceptionCount: 0, ambiguousMatchCount: 0, datesMissingCount: 0, ...over });
const preview = (over: object) => ({ headlineTotalPaise: 0, headlineEngineResultRef: "e30e0993-0000", affectedSkuCount: 0, affectedSkuCountUnavailable: false, revealedFinding: null, lockedFindingsCount: 0, ...over });

describe("Leak Shield / Reconciliation", () => {
  it("does not call 'nothing reconciled' a clean result, and says why when lines have no date", async () => {
    next = () => reply(recon({ datesMissingCount: 100 }));
    await run(<ReconcileSection getToken={token} />, "Run reconciliation");
    expect(await screen.findByRole("status")).toHaveTextContent(/Nothing could be reconciled for MEESHO.*not a clean result.*100 uploaded line\(s\) have no date/);
    expect(screen.queryByText("No leak findings for this period.")).toBeNull();
  });

  it("asks for both reports when no lines exist at all", async () => {
    next = () => reply(recon({}));
    await run(<ReconcileSection getToken={token} />, "Run reconciliation");
    expect(await screen.findByRole("status")).toHaveTextContent(/Upload both reports for these dates/);
  });

  it("says 'no leak findings' only when lines were actually matched", async () => {
    next = () => reply(recon({ matchCount: 40 }));
    await run(<ReconcileSection getToken={token} />, "Run reconciliation");
    expect(await screen.findByText("No leak findings for this period.")).toBeInTheDocument();
  });

  it("shows a plan limit in words rather than 'Could not run'", async () => {
    next = () => reply("cfo entitlement required", 402);
    await run(<ReconcileSection getToken={token} />, "Run reconciliation");
    expect(await screen.findByRole("alert")).toHaveTextContent(/plan does not include this/);
  });
});

describe("CFO Preview", () => {
  it("does not offer an upgrade for zero locked findings", async () => {
    next = () => reply(preview({}));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    expect(await screen.findByText("No leak finding was reported for this period.")).toBeInTheDocument();
    expect(screen.queryByText(/locked — upgrade/)).toBeNull();
  });

  it("offers the upgrade only when findings are really locked", async () => {
    next = () => reply(preview({ lockedFindingsCount: 3, headlineTotalPaise: 250000 }));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    expect(await screen.findByText("3 more finding(s) locked — upgrade to see them all.")).toBeInTheDocument();
  });

  it("a server failure is a sentence, not a raw error", async () => {
    next = () => reply("boom", 500);
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("CFO Preview: what a total of zero does and does not say", () => {
  it("keeps a real 0 as ₹0.00 with its reference, never turns it into 'Not available', and says what the preview cannot tell", async () => {
    next = () => reply(preview({}));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    const total = await screen.findByTestId("preview-total");
    expect(total).toHaveTextContent("₹0.00");
    expect(total).toHaveTextContent("e30e0993");
    expect(total).not.toHaveTextContent("Not available");
    const note = screen.getByTestId("preview-zero-note");
    expect(note).toHaveTextContent("does not show how many lines were checked");
    expect(note).toHaveTextContent("does not tell you whether reports were uploaded for these dates");
    expect(note).toHaveTextContent("Run Leak Shield");
  });

  it("does not claim that uploaded data was examined", async () => {
    next = () => reply(preview({}));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    await screen.findByTestId("preview-total");
    expect(screen.getByTestId("preview-result").textContent).not.toMatch(/in the data uploaded|clean|no discrepancies found|all clear/i);
  });

  it("shows no zero note when there is a finding, and shows the total exactly as sent", async () => {
    next = () => reply(preview({ headlineTotalPaise: 250000, affectedSkuCount: 1, revealedFinding: { leakCategory: "FEE_OVERCHARGE", severity: "HIGH", amountPaise: 250000, sku: "S1" }, lockedFindingsCount: 0 }));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    expect(await screen.findByTestId("preview-total")).toHaveTextContent("₹2500.00");
    expect(screen.queryByTestId("preview-zero-note")).toBeNull();
    expect(screen.queryByText("No leak finding was reported for this period.")).toBeNull();
    expect(screen.getByTestId("preview-skus")).toHaveTextContent("Affected SKUs: 1");
  });

  it("shows 'Not available' for a total the backend did not give, and no zero note", async () => {
    next = () => reply(preview({ headlineTotalPaise: null, headlineEngineResultRef: null }));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    const total = await screen.findByTestId("preview-total");
    expect(total).toHaveTextContent("Not available");
    expect(total).not.toHaveTextContent("₹0.00");
    expect(screen.queryByTestId("preview-zero-note")).toBeNull();
  });

  it("shows the backend's 'SKU not tracked' flag in words, never as the word 'true', and keeps a real 0 count as 0", async () => {
    next = () => reply(preview({ headlineTotalPaise: 250000, affectedSkuCount: null, affectedSkuCountUnavailable: true, revealedFinding: { leakCategory: "FEE_OVERCHARGE", severity: "HIGH", amountPaise: 250000, sku: null } }));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    const skus = await screen.findByTestId("preview-skus");
    expect(skus).toHaveTextContent("Not available: the findings do not say which SKU they belong to.");
    expect(skus.textContent).not.toMatch(/true|UNAVAILABLE/);
    expect(skus.textContent).not.toMatch(/Affected SKUs:\s*0/);
  });

  it("shows an honest count of 0 when there are no findings and the flag is false", async () => {
    next = () => reply(preview({}));
    await run(<CfoPreviewSection getToken={token} />, "Load preview");
    expect(await screen.findByTestId("preview-skus")).toHaveTextContent("Affected SKUs: 0");
  });
});
