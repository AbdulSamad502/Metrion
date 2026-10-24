import { describe, expect, it } from "vitest";
import { demoHealth } from "@/lib/demo/fixtures/health";

describe("sample health entries", () => {
  const { entries } = demoHealth();

  it("has the Contribution profit headline in BS_PNL_LATEST, with a register, as-of and ref on every figure", () => {
    const pnl = entries.find((e) => e.key === "BS_PNL_LATEST")!;
    const headline = pnl.presentation!.figures.find((f) => f.label === "Contribution profit")!;
    expect(headline.value).toBe("₹142,860.00");
    expect(headline.register).toBe("VERIFIED");
    for (const e of entries) for (const f of e.presentation?.figures ?? []) {
      expect(f.register).toBeTruthy();
      expect(f.as_of).toBeTruthy();
      expect(f.ref.id.startsWith("demo-")).toBe(true);
    }
  });

  it("keeps every entry's keys identical to a real entry and mixes statuses honestly", () => {
    for (const e of entries) expect(Object.keys(e).sort()).toEqual(["asOf", "key", "period", "presentation", "previewHint", "status"]);
    expect(new Set(entries.map((e) => e.status))).toEqual(new Set(["AVAILABLE", "PARTIAL", "UNAVAILABLE"]));
    const unavailable = entries.find((e) => e.status === "UNAVAILABLE")!;
    expect(unavailable.presentation).toBeNull();
    expect(unavailable.previewHint).toBeTruthy(); // missing is said in words, never shown as zero
  });

  it("uses the backend period label (start/end ISO dates) and no zero stands in for a missing figure", () => {
    expect(entries.find((e) => e.key === "BS_PNL_LATEST")!.period).toMatch(/^\d{4}-\d{2}-\d{2}\/\d{4}-\d{2}-\d{2}$/);
    for (const e of entries) for (const f of e.presentation?.figures ?? []) expect(f.value).not.toMatch(/^₹0(\.00)?$/);
  });
});
