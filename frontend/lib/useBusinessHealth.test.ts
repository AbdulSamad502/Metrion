import { describe, expect, it } from "vitest";
import { daysSince, latestAsOf, STALE_AFTER_DAYS } from "@/lib/useBusinessHealth";

const NOW = Date.parse("2026-10-10T12:00:00Z");

describe("data freshness (date comparison only)", () => {
  it("counts whole days since a saved result's as-of date", () => {
    expect(daysSince("2026-10-10", NOW)).toBe(0);
    expect(daysSince("2026-10-09", NOW)).toBe(1);
    expect(daysSince("2026-10-01T00:00:00Z", NOW)).toBe(9);
  });
  it("is null for a missing or unreadable date, and never negative", () => {
    expect(daysSince(null, NOW)).toBeNull();
    expect(daysSince("not a date", NOW)).toBeNull();
    expect(daysSince("2026-12-01", NOW)).toBe(0);
  });
  it("uses the same 7-day threshold as the competitor view", () => {
    expect(STALE_AFTER_DAYS).toBe(7);
  });
  it("picks the newest as-of among the saved results", () => {
    expect(latestAsOf([{ asOf: "2026-10-01" }, { asOf: "2026-10-05" }, { asOf: null }] as never)).toBe("2026-10-05");
    expect(latestAsOf([])).toBeNull();
  });
});
