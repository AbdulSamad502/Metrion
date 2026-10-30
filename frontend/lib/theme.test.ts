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

describe("first-paint script", () => {
  const run = async (path: string, stored: string | null) => {
    const { themeInitScript } = await import("./theme");
    document.documentElement.removeAttribute("data-theme");
    window.history.replaceState(null, "", path);
    window.localStorage.clear();
    if (stored) window.localStorage.setItem("metrion.theme", stored);
    new Function(themeInitScript)();
    return document.documentElement.getAttribute("data-theme");
  };
  it("sets light inside the signed-in app when light was chosen", async () => {
    expect(await run("/dashboard", "light")).toBe("light");
    expect(await run("/dashboard/cfo", "light")).toBe("light");
    expect(await run("/settings", "light")).toBe("light");
  });
  it("leaves the CEO Hub, marketing and sign-in pages dark", async () => {
    expect(await run("/dashboard/ceo-hub", "light")).toBeNull();
    expect(await run("/", "light")).toBeNull();
    expect(await run("/sign-in", "light")).toBeNull();
    expect(await run("/dashboardx", "light")).toBeNull();
  });
  it("does nothing for dark or an unset choice, and never throws when storage is blocked", async () => {
    expect(await run("/dashboard", "dark")).toBeNull();
    expect(await run("/dashboard", null)).toBeNull();
    window.history.replaceState(null, "", "/dashboard");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { themeInitScript } = await import("./theme");
    expect(() => new Function(themeInitScript)()).not.toThrow();
  });
});
