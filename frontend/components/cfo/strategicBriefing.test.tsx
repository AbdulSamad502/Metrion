import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StrategicBriefingSection } from "@/components/cfo/sections/ImportAndGoalSections";

const gap = (reason: string, metric = "LANDED_COST") => ({ category: "DATA_GAP", severityRank: 1, severityLabel: "OPEN", recommendedActionType: "PROVIDE_INPUT", headline: `Missing: supplier.quote (blocks ${metric})`, evidence: { label: "supplier.quote", textValue: reason, register: "MANUAL" } });
afterEach(() => vi.unstubAllGlobals());

async function build(signals: object[]) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ signals, narrative: null, generatedAt: "2026-10-11T00:00:00Z", narrationSafety: null }), { status: 200, headers: { "Content-Type": "application/json" } })));
  render(<StrategicBriefingSection getToken={async () => "t"} />);
  const user = userEvent.setup();
  for (const label of ["Period start", "Period end", "As-of date"]) await user.type(screen.getByLabelText(label), "2026-09-30");
  await user.click(screen.getByRole("button", { name: "Build briefing" }));
}

describe("Strategic briefing: missing inputs", () => {
  it("lists the same missing input once however many identical signals arrive", async () => {
    await build([gap("No active quote exists for SKU-1."), gap("No active quote exists for SKU-1.")]);
    expect(await screen.findAllByText(/Missing: supplier\.quote \(blocks LANDED_COST\)/)).toHaveLength(1);
  });

  it("keeps requests that differ, and shows their reason so they can be told apart", async () => {
    await build([gap("No active quote exists for SKU-1."), gap("No active quote exists for SKU-2.")]);
    expect(await screen.findAllByText(/Missing: supplier\.quote/)).toHaveLength(2);
    expect(screen.getByText(/No active quote exists for SKU-1\./)).toBeInTheDocument();
    expect(screen.getByText(/No active quote exists for SKU-2\./)).toBeInTheDocument();
  });
});
