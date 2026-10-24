import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getTheme, resetThemeForTests, setTheme, subscribeTheme } from "./theme";

beforeEach(() => {
  window.localStorage.clear();
  resetThemeForTests();
});
afterEach(() => vi.restoreAllMocks());

describe("theme choice", () => {
  it("is dark until the seller picks light", () => {
    expect(getTheme()).toBe("dark");
  });
  it("remembers light, tells subscribers, and returns to dark", () => {
    const seen = vi.fn();
    const off = subscribeTheme(seen);
    setTheme("light");
    expect(getTheme()).toBe("light");
    expect(window.localStorage.getItem("metrion.theme")).toBe("light");
    expect(seen).toHaveBeenCalledTimes(1);
    resetThemeForTests();
    expect(getTheme()).toBe("light"); // read back from storage
    setTheme("dark");
    expect(getTheme()).toBe("dark");
    off();
  });
  it("still applies the choice when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    setTheme("light");
    expect(getTheme()).toBe("light");
  });
});
