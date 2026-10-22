import { describe, expect, it } from "vitest";
import { countToDigits, formatBps, formatPaise, formatRoas, paiseToInputText, percentToBps, rupeesToPaise } from "@/lib/pnlText";

describe("typed text -> integer strings (no float, no rounding)", () => {
  it("reads rupees to paise exactly", () => {
    expect(rupeesToPaise("1,180.50")).toEqual({ ok: true, value: "118050" });
    expect(rupeesToPaise("₹ 25")).toEqual({ ok: true, value: "2500" });
    expect(rupeesToPaise("0.5")).toEqual({ ok: true, value: "50" });
    expect(rupeesToPaise("0")).toEqual({ ok: true, value: "0" });
    expect(rupeesToPaise("007.07")).toEqual({ ok: true, value: "707" });
  });
  it("refuses what it cannot read exactly instead of rounding it", () => {
    for (const bad of ["10.005", "-5", "", "1e3", "12abc", "1.2.3", "100,000,000,000", "NaN", "Infinity", "0x10"]) expect(rupeesToPaise(bad).ok, bad).toBe(false);
  });
  it("keeps the largest accepted amount exact, as a string, and refuses anything above the API ceiling", () => {
    expect(rupeesToPaise("99,999,999,999.99")).toEqual({ ok: true, value: "9999999999999" });
    expect(rupeesToPaise("100,000,000,000").ok).toBe(false);
  });
  it("reads percentages to basis points, up to 100", () => {
    expect(percentToBps("12.5")).toEqual({ ok: true, value: "1250" });
    expect(percentToBps("18%")).toEqual({ ok: true, value: "1800" });
    expect(percentToBps("100")).toEqual({ ok: true, value: "10000" });
    expect(percentToBps("0")).toEqual({ ok: true, value: "0" });
    for (const bad of ["100.01", "101", "abc", "-1", "1.234", ""]) expect(percentToBps(bad).ok, bad).toBe(false);
  });
  it("reads whole counts only", () => {
    expect(countToDigits("1,200")).toEqual({ ok: true, value: "1200" });
    for (const bad of ["12.5", "-3", "", "1e3", "1234567890"]) expect(countToDigits(bad).ok, bad).toBe(false);
  });
});

describe("integer strings -> readable text", () => {
  it("formats paise with Indian grouping and a real minus sign", () => {
    expect(formatPaise("123456789")).toBe("₹12,34,567.89");
    expect(formatPaise("-5")).toBe("−₹0.05");
    expect(formatPaise("0")).toBe("₹0.00");
    expect(formatPaise("49200")).toBe("₹492.00");
    expect(formatPaise("9007199254740993")).toBe("₹9,00,71,99,25,47,409.93");
  });
  it("shows anything that is not an integer string as unavailable, never as a guess", () => {
    for (const bad of [null, undefined, "", "1.5", "abc", "1e3"]) expect(formatPaise(bad as string | null)).toBe("Not available");
    expect(formatBps(null)).toBe("Not available");
  });
  it("formats basis points and ROAS", () => {
    expect(formatBps("4920")).toBe("49.20%");
    expect(formatBps("-150")).toBe("−1.50%");
    expect(formatBps("5")).toBe("0.05%");
    expect(formatRoas("50000")).toBe("5.00x");
    expect(formatRoas("23456")).toBe("2.3456x");
    expect(formatRoas("2500")).toBe("0.25x");
  });
});

describe("solved price -> field text", () => {
  it("writes what a seller would type, and it reads back to the same paise", () => {
    for (const p of ["14014", "14000", "5", "100", "9999999999999", "0"]) {
      const text = paiseToInputText(p);
      expect(rupeesToPaise(text)).toEqual({ ok: true, value: p });
    }
    expect(paiseToInputText("14014")).toBe("140.14");
    expect(paiseToInputText("14000")).toBe("140");
    expect(paiseToInputText("5")).toBe("0.05");
  });
  it("gives nothing for anything that is not a non-negative integer string", () => {
    for (const bad of [null, undefined, "", "-5", "1.5", "abc"]) expect(paiseToInputText(bad as string | null)).toBe("");
  });
});
