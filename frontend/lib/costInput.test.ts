import { describe, expect, it } from "vitest";
import { costReady, costToApi, EMPTY_COST, rupeesToPaise } from "@/lib/costInput";

describe("rupeesToPaise: exact, integer-only", () => {
  it.each([
    ["0", 0], ["49.50", 4950], ["1,299.5", 129950], ["1.05", 105], ["1.1", 110], [" 7 ", 700], ["100000", 10000000],
  ])("parses %s", (text, paise) => expect(rupeesToPaise(text)).toBe(paise));

  it.each(["", "abc", "-5", "1.005", "1.", ".5", "1e3", "1,2,3.456", "₹5", "5.555"])("rejects %j instead of rounding or guessing", (text) =>
    expect(rupeesToPaise(text)).toBeNull(),
  );

  it("does not suffer float error on classic cases", () => {
    expect(rupeesToPaise("1.15")).toBe(115); // parseFloat(1.15) * 100 is 114.99999999999999
    expect(rupeesToPaise("0.29")).toBe(29); // 0.29 * 100 is 28.999999999999996
    expect(rupeesToPaise("4.35")).toBe(435);
  });
});

describe("a cost has no default", () => {
  it("an unanswered cost is not ready and cannot be turned into a number", () => {
    expect(costReady(EMPTY_COST)).toBe(false);
    expect(() => costToApi(EMPTY_COST)).toThrow();
  });

  it("an amount mode with no valid amount is not ready", () => {
    expect(costReady({ mode: "amount", amount: "", reason: "" })).toBe(false);
    expect(costReady({ mode: "amount", amount: "12.345", reason: "" })).toBe(false);
  });

  it("each of the three explicit states maps to its own API shape", () => {
    expect(costToApi({ mode: "amount", amount: "49.50", reason: "" })).toEqual({ paise: 4950, reason: null });
    expect(costToApi({ mode: "none", amount: "ignored", reason: "" })).toEqual({ paise: 0, reason: null });
    expect(costToApi({ mode: "unknown", amount: "", reason: "supplier has not told me" })).toEqual({ paise: null, reason: "supplier has not told me" });
    expect(costToApi({ mode: "unknown", amount: "", reason: "  " })).toEqual({ paise: null, reason: null });
  });
});
