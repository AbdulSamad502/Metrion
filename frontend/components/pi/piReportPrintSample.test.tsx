import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/demo/mode", () => ({ useDemo: () => true }));

import { PiReportPrint } from "@/components/pi/PiReportPrint";
import type { PiClient } from "@/lib/piShowcase";

const client = {
  history: async () => ({ items: [] }),
  report: async () => ({
    runId: "11111111-1111-4111-8111-111111111111", status: "COMPLETE", pinned: false, pinnedAt: null, completedAt: null, caseSaved: true,
    brief: { category: "kitchen", budgetPaise: null, targetPriceMinPaise: null, targetPriceMaxPaise: null, marketplaces: [] },
    products: [], overall: null, cfoRefs: [], gaps: [], unavailable: [], investigationId: null,
  }),
  pin: async () => ({ runId: "x", pinned: true }),
  unpin: async () => ({ runId: "x", pinned: false }),
} as unknown as PiClient;

describe("PI print report in sample-data mode", () => {
  it("says on the page itself, so it is on the printed copy too, that the report is fictional", async () => {
    render(<PiReportPrint client={client} runId="11111111-1111-4111-8111-111111111111" />);
    expect(await screen.findByRole("note")).toHaveTextContent("SAMPLE DATA: this report is fictional and is not a real research result.");
  });
});
