import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV_GROUPS, PAGE_COPY, allNavItems, isActive, pageTitle } from "@/lib/navigation";

// Round 9 R9-1: the Expense Tracker is a dedicated dashboard at /dashboard/cfo/expenses, linked from the CFO page; the sidebar is unchanged and there is no new top-level
// product or agent.

describe("the Expense Tracker route", () => {
  it("has a title and description from PAGE_COPY, and the page uses them instead of hand-written wording", () => {
    expect(PAGE_COPY["cfo-expenses"].title).toBe("Expense Tracker");
    const src = readFileSync(join(process.cwd(), "app/dashboard/cfo/expenses/page.tsx"), "utf8");
    expect(src).toContain('PAGE_COPY["cfo-expenses"]');
    expect(src).not.toMatch(/<DashboardShell[^>]*title="/);
  });

  it("names the route in the browser tab", async () => {
    const layout = await import("@/app/dashboard/cfo/expenses/layout");
    expect(layout.metadata.title).toBe(pageTitle("cfo-expenses"));
  });

  it("leaves the sidebar unchanged and keeps Profit & Finance highlighted on the new route", () => {
    expect(NAV_GROUPS.map((g) => g.items.map((i) => i.label))).toEqual([
      ["Overview", "Ask Metrion", "Action Center"],
      ["Products", "Competitors", "Profit & Finance", "Profit Calculator", "Listings & Marketing"],
    ]);
    const cfo = allNavItems().find((i) => i.id === "cfo")!;
    expect(isActive(cfo, "/dashboard/cfo/expenses")).toBe(true);
    expect(allNavItems().some((i) => i.href === "/dashboard/cfo/expenses")).toBe(false);
  });

  it("is linked from the CFO page", () => {
    const src = readFileSync(join(process.cwd(), "app/dashboard/cfo/page.tsx"), "utf8");
    expect(src).toContain("/dashboard/cfo/expenses");
  });
});

// The dashboard does no money maths in the browser: no number parsing, rounding, locale or currency formatting, or float helpers. Amounts the seller types are parsed to
// integer-paise STRINGS by rupeesToPaise and shown by formatPaise; every total is the backend's (the engine feed). The same guard as the Profit Calculator's.
describe("the Expense Tracker does no money maths in the browser", () => {
  const ROOT = process.cwd();
  const files = ["lib/expenseLedger.ts", "app/dashboard/cfo/expenses/page.tsx", ...readdirSync(join(ROOT, "components/expenses")).filter((f) => /\.tsx$/.test(f) && !/\.test\./.test(f)).map((f) => `components/expenses/${f}`)];
  const BANNED = [/toFixed/, /parseFloat/, /parseInt/, /\bNumber\(/, /Math\./, /Intl\.NumberFormat/, /toLocaleString/, /\bBigInt\b/, /\bDecimal\b/];
  for (const file of files) {
    it(file, () => {
      const src = readFileSync(join(ROOT, file), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
      for (const banned of BANNED) expect(src, `${file} contains ${banned}`).not.toMatch(banned);
    });
  }
  it("never adds, subtracts or compares an amount field", () => {
    for (const file of files.filter((f) => f.startsWith("components/"))) {
      const src = readFileSync(join(ROOT, file), "utf-8");
      expect(src, file).not.toMatch(/\.(?:amountPaise|paise|amount_paise)\s*[-+*/<>]/);
      expect(src, file).not.toMatch(/[-+*/]\s*\w+\.(?:amountPaise|paise)\b/);
      expect(src, file).not.toMatch(/\.reduce\(/);
    }
  });
});
