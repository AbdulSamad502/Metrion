import { describe, expect, it } from "vitest";
import { rupees } from "@/components/cfo/primitives";

/** `rupees()` divides integer paise by 100 and rounds to two places with `toFixed`. The inputs are integers, so the result should be exactly the decimal that integer
 * formatting would give. This pins that: an exact, integer-only formatter built from BigInt is the reference, and the two must agree. (It was also checked
 * exhaustively for every integer paise from 0 to 50,000,000 and for 5,000,000 random values up to 10^13 paise: no difference.) It pins today's behaviour; it does not
 * change it. Whether to replace the float division with integer-only formatting and Indian digit grouping is a product decision, kept separate. */
const exact = (p: number): string => {
  const digits = String(BigInt(Math.abs(p))).padStart(3, "0");
  return `₹${p < 0 ? "-" : ""}${digits.slice(0, -2)}.${digits.slice(-2)}`;
};

describe("rupees() on integer paise", () => {
  it.each([0, 1, 5, 9, 10, 99, 100, 101, 105, 199, 999, 1000, 12345, 49900, 100000, 123456789, 1_000_000_001, 9_999_999_999, 123_456_789_012, 4_503_599_627_370])(
    "%i paise reads exactly",
    (p) => expect(rupees(p)).toBe(exact(p)),
  );
  it("matches the exact formatter across a dense run of values, including every half-rupee boundary", () => {
    for (let p = 0; p <= 200_000; p++) expect(rupees(p)).toBe(exact(p));
  });
  it("shows a missing value as a dash, never as zero", () => {
    expect(rupees(null)).toBe("—");
  });
});
