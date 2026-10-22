import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrendChart } from "@/components/cfo/v2/charts/TrendChart";
import { DataTable } from "@/components/cfo/v2/tables/DataTable";
import { FigureView } from "@/components/cfo/v2/trust/FigureView";
import type { Completeness } from "@/lib/cfoV2/types";
import { fig } from "@/test-support/cfoV2Fixtures";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

/** AC-DI4: the words the product must not use (cfo-dashboard-implementation.md §3) never appear in any v2 component, in any trust state. */
const BANNED = [/recoverable/i, /recovered/i, /ready to dispute/i, /autonomous/i, /auto-generated/i, /cash in bank/i, /liquid cash/i, /runway/i, /\bLive\b/];
const STATES: Completeness[] = ["COMPLETE", "PARTIAL", "PROVISIONAL", "ESTIMATED", "UNAVAILABLE"];

describe("no banned wording in any v2 component or state", () => {
  for (const c of STATES) {
    it(`FigureView ${c}`, () => {
      const unavailable = c === "UNAVAILABLE";
      const { container } = render(
        <FigureView figure={fig({ completeness: c, valueDisplay: unavailable ? null : "₹10.00", missingInputs: unavailable ? [{ field: "f", why: "an input is missing" }] : [], adSpendStatus: "UNKNOWN" })} />,
      );
      for (const b of BANNED) expect(container.textContent ?? "", String(b)).not.toMatch(b);
    });
  }
  it("TrendChart and DataTable", () => {
    const a = render(<TrendChart title="Contribution Profit by month" points={[{ label: "Sep", plot: 1, display: "₹10.00", status: "ESTIMATED" }]} />);
    const b = render(<DataTable columns={[{ key: "k", header: "SKU", render: () => "x" }]} rows={[]} rowKey={() => "k"} page={1} pageCount={1} total={0} onSort={() => {}} onPage={() => {}} caption="t" />);
    for (const t of [a.container.textContent ?? "", b.container.textContent ?? ""]) for (const w of BANNED) expect(t).not.toMatch(w);
  });
  it("headings use the defined terms, never a bare Profit, Revenue or Sales", () => {
    const { container } = render(<FigureView figure={fig({ label: "Net Realized Revenue" })} />);
    const label = container.querySelector(".t-label")?.textContent ?? "";
    expect(["Profit", "Revenue", "Sales"]).not.toContain(label.trim());
  });
});
