import { describe, expect, it } from "vitest";
import { bandOf, flowShares, goalShare, periodDays, periodLabel, readLeak, weight } from "./format";

describe("overview formatting", () => {
  it("reads a backend money string only to size things", () => {
    expect(weight("₹1,42,860.00")).toBe(142860);
    expect(weight("−₹3,210.00")).toBe(-3210);
    expect(weight("Unavailable")).toBeNull();
    expect(weight(undefined)).toBeNull();
  });

  it("sizes the revenue bar, and refuses when the figures do not fit together", () => {
    const s = flowShares("₹1,000.00", "₹250.00", "₹100.00")!;
    expect(s.fees).toBeCloseTo(0.25);
    expect(s.profit).toBeCloseTo(0.1);
    expect(s.fees + s.profit + s.rest).toBeCloseTo(1);
    expect(flowShares("₹1,000.00", "₹900.00", "₹200.00")).toBeNull(); // more than the revenue
    expect(flowShares("₹1,000.00", "₹250.00", "−₹10.00")).toBeNull(); // a loss is not drawn as a share
    expect(flowShares("₹1,000.00", undefined, "₹100.00")).toBeNull(); // a missing figure is never a zero
  });

  it("caps a goal meter at full and ignores a missing goal", () => {
    expect(goalShare("₹200.00", "₹100.00")).toBe(1);
    expect(goalShare("₹50.00", "₹100.00")).toBe(0.5);
    expect(goalShare("₹50.00", undefined)).toBeNull();
  });

  it("reads bands and leak labels, falling back to the backend's own words", () => {
    expect(bandOf("WATCH (classified by the engine)")).toBe("WATCH");
    expect(bandOf("At risk")).toBe("AT_RISK");
    expect(bandOf("something else")).toBeNull();
    const f = { label: "FEE_OVERCHARGE — MEESHO [LOW]", value: "₹1,480.00", register: "DERIVED", as_of: null, note: null, ref: { kind: "E", id: "1", as_of: "" } };
    expect(readLeak(f)).toMatchObject({ title: "Fee overcharge", where: "Meesho", severity: "Low", amount: "₹1,480.00" });
    expect(readLeak({ ...f, label: "A leak nobody formatted" })).toMatchObject({ title: "A leak nobody formatted", severity: null });
  });

  it("writes periods as calendar days without a time zone", () => {
    expect(periodLabel("2026-09-01/2026-09-30")).toBe("1 Sep – 30 Sep");
    expect(periodDays("2026-09-01/2026-09-30")).toBe(30);
    expect(periodLabel(null)).toBeNull();
  });
});
