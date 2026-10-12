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
  await user.type(screen.getAllByLabelText("Marketplace")[0], "MEESHO");
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
    expect(await screen.findByText(/No leak finding to show in the data uploaded/)).toBeInTheDocument();
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
