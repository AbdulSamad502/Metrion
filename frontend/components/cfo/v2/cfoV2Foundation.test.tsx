import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TrendChart } from "@/components/cfo/v2/charts/TrendChart";
import { FilterBar } from "@/components/cfo/v2/filters/FilterBar";
import { DataTable, FigureCell } from "@/components/cfo/v2/tables/DataTable";
import { FigureView } from "@/components/cfo/v2/trust/FigureView";
import { DEFAULT_FILTERS, apiQuery, parseFilters, serializeFilters } from "@/lib/cfoV2/filters";
import type { Completeness } from "@/lib/cfoV2/types";
import { fig } from "@/test-support/cfoV2Fixtures";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

describe("FigureView draws every trust state in words, never colour alone", () => {
  it("COMPLETE is the only confirmed actual: value, badge, register, no caveat line", () => {
    render(<FigureView figure={fig()} />);
    expect(screen.getByText("₹1,23,456.00")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.queryByText(/can change|estimate from history/i)).toBeNull();
  });

  for (const c of ["PARTIAL", "PROVISIONAL", "ESTIMATED"] as Completeness[]) {
    it(`${c} carries its badge AND a one-line reason`, () => {
      render(<FigureView figure={fig({ completeness: c })} />);
      expect(screen.getByText(c === "PARTIAL" ? "Partial" : c === "PROVISIONAL" ? "Provisional" : "Estimated")).toBeInTheDocument();
      expect(screen.getByText(c === "PARTIAL" ? /missing/i : c === "PROVISIONAL" ? /can change/i : /estimate from history/i)).toBeInTheDocument(); // the reason line, besides the badge
    });
  }

  it("a server status note replaces the generic reason and is shown verbatim", () => {
    render(<FigureView figure={fig({ completeness: "PROVISIONAL", statusNotes: ["Provisional: 3 expenses are unclassified"] })} />);
    expect(screen.getByText("Provisional: 3 expenses are unclassified")).toBeInTheDocument();
  });

  it("UNAVAILABLE shows a dash and the reason, offers 'Provide this', and never shows 0", async () => {
    const onProvide = vi.fn();
    render(<FigureView figure={fig({ valueDisplay: null, completeness: "UNAVAILABLE", register: "UNAVAILABLE", missingInputs: [{ field: "cogs", why: "cost per unit is missing", dataRequestId: "dr1" }] })} onProvide={onProvide} />);
    expect(screen.getByLabelText("Contribution Profit: not available")).toHaveTextContent("—");
    expect(screen.getByText("cost per unit is missing")).toBeInTheDocument();
    expect(screen.queryByText(/^0$|₹0/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Provide this" }));
    expect(onProvide).toHaveBeenCalledWith("dr1");
  });

  it("completeness and register are separate axes: a DERIVED figure can be PROVISIONAL, and both show", () => {
    render(<FigureView figure={fig({ completeness: "PROVISIONAL", register: "DERIVED" })} />);
    expect(screen.getByText("Provisional")).toBeInTheDocument();
    expect(screen.getByText(/derived|calculated/i)).toBeInTheDocument();
  });

  it("advertising status is spelled out when present", () => {
    render(<FigureView figure={fig({ adSpendStatus: "MISSING_COVERAGE" })} />);
    expect(screen.getByText(/does not cover the whole period/i)).toBeInTheDocument();
  });

  it("the trust popover is a button (keyboard), lists source, refs, exclusions and missing inputs", async () => {
    render(<FigureView figure={fig({ exclusions: [{ reason: "Held duplicates", count: 4, amountDisplay: "₹800.00" }], missingInputs: [{ field: "x", why: "Flipkart fees are not uploaded" }] })} />);
    const btn = screen.getByRole("button", { name: "Why this figure?" });
    expect(btn).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(btn);
    const region = screen.getByRole("region", { name: /How Contribution Profit was produced/ });
    expect(within(region).getByText("Uploaded settlement reports")).toBeInTheDocument();
    expect(within(region).getByText("eng_abc")).toBeInTheDocument();
    expect(within(region).getByText(/Held duplicates: 4/)).toBeInTheDocument();
    expect(within(region).getByText(/Flipkart fees are not uploaded/)).toBeInTheDocument();
  });
});

describe("filters live in the URL and are allow-listed", () => {
  it("round-trips", () => {
    const f = { from: "2026-09-01", to: "2026-09-30", marketplace: "MEESHO" as const, sku: "A-1" };
    expect(parseFilters(serializeFilters(f))).toEqual(f);
    expect(serializeFilters(DEFAULT_FILTERS)).toBe("");
  });
  it("drops a bad marketplace, bad dates, an inverted range and an over-long SKU", () => {
    expect(parseFilters("?marketplace=EBAY").marketplace).toBe("ALL");
    expect(parseFilters("?from=yesterday&to=2026-13-99x")).toMatchObject({ from: null, to: null });
    expect(parseFilters("?from=2026-10-01&to=2026-09-01")).toMatchObject({ from: null, to: null });
    expect(parseFilters(`?sku=${"x".repeat(200)}`).sku).toHaveLength(60);
    expect(parseFilters("?tenant_id=abc")).toEqual(DEFAULT_FILTERS); // a client never supplies a tenant
  });
  it("builds the API query with paging and sort only when given", () => {
    expect(apiQuery({ ...DEFAULT_FILTERS, marketplace: "AMAZON" }, { page: 2, pageSize: 50, sort: "nrr", dir: "desc" })).toBe("marketplace=AMAZON&page=2&pageSize=50&sort=nrr&dir=desc");
  });
  it("the bar reports changes", async () => {
    const onChange = vi.fn();
    render(<FilterBar filters={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "FLIPKART");
    expect(onChange).toHaveBeenCalledWith({ marketplace: "FLIPKART" });
  });
});

describe("DataTable never sorts or slices itself", () => {
  const cols = [
    { key: "sku", header: "SKU", sortable: true, render: (r: { sku: string; v: { display: string | null; status: Completeness } }) => r.sku },
    { key: "v", header: "Contribution Profit", render: (r: { sku: string; v: { display: string | null; status: Completeness } }) => <FigureCell cell={r.v} /> },
  ];
  const rows = [
    { sku: "B", v: { display: "₹20.00", status: "COMPLETE" as const } },
    { sku: "A", v: { display: null, status: "UNAVAILABLE" as const } },
    { sku: "C", v: { display: "₹5.00", status: "PROVISIONAL" as const } },
  ];
  it("keeps the server's row order, shows dash for unavailable and a badge for provisional", () => {
    render(<DataTable columns={cols} rows={rows} rowKey={(r) => r.sku} page={1} pageCount={3} total={9} onSort={() => {}} onPage={() => {}} caption="SKU profit" />);
    const body = screen.getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(body[0]).toContain("B");
    expect(body[1]).toContain("—");
    expect(body[2]).toContain("Provisional");
    expect(screen.getByText(/Page 1 of 3 · 9 rows/)).toBeInTheDocument();
  });
  it("asks the parent for another sort or page", async () => {
    const onSort = vi.fn();
    const onPage = vi.fn();
    render(<DataTable columns={cols} rows={rows} rowKey={(r) => r.sku} page={2} pageCount={3} total={9} sort="sku" dir="desc" onSort={onSort} onPage={onPage} caption="SKU profit" />);
    expect(screen.getByRole("columnheader", { name: /SKU/ })).toHaveAttribute("aria-sort", "descending");
    await userEvent.click(screen.getByRole("button", { name: /SKU/ }));
    expect(onSort).toHaveBeenCalledWith("sku", "asc");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(3);
  });
  it("shows an empty state, not a zero row", () => {
    render(<DataTable columns={cols} rows={[]} rowKey={(r) => r.sku} page={1} pageCount={1} total={0} onSort={() => {}} onPage={() => {}} caption="SKU profit" />);
    expect(screen.getByText(/Nothing to show/)).toBeInTheDocument();
  });
});

describe("Recharts compatibility gate (React 19 / Next 16)", () => {
  it("a chart wrapper renders with an equivalent table, a gap for unavailable, and the server's display strings", () => {
    render(
      <TrendChart
        title="Contribution Profit by month"
        points={[
          { label: "Aug", plot: 3, display: "₹30.00", status: "COMPLETE" },
          { label: "Sep", plot: null, display: null, status: "UNAVAILABLE" },
          { label: "Oct", plot: 2, display: "₹20.00", status: "PROVISIONAL" },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: /Contribution Profit by month/ })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /as a table/ });
    expect(within(table).getByText("₹30.00")).toBeInTheDocument();
    expect(within(table).getByLabelText("not available")).toBeInTheDocument();
    expect(within(table).getByText("Provisional")).toBeInTheDocument();
  });
});
