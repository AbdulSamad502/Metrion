import { describe, expect, it } from "vitest";
import { parseProgress } from "@/lib/clarificationProgress";

describe("parseProgress", () => {
  it("reads the backend's '(N of M)' prefix and nothing else", () => {
    expect(parseProgress("(8 of 11) What is the shipping cost per unit?")).toEqual({ step: 8, total: 11, percent: 64 });
    expect(parseProgress("(1 of 3) Which SKU?")).toEqual({ step: 1, total: 3, percent: 0 });
  });
  it("shows no progress when the question carries none, or the numbers are impossible", () => {
    expect(parseProgress("Which competitor did you mean?")).toBeNull();
    expect(parseProgress("(0 of 3) x")).toBeNull();
    expect(parseProgress("(4 of 3) x")).toBeNull();
    expect(parseProgress("I could not read that. (2 of 3) later in the text")).toBeNull();
  });
});
