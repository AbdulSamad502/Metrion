import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV_GROUPS, PAGE_COPY, allNavItems, isActive, pageTitle } from "@/lib/navigation";

// The Expense Tracker is a dedicated dashboard at /dashboard/cfo/expenses with its own sidebar entry (owner instruction 2026-10-22, superseding R9-1's "sidebar unchanged"),
// still linked from the CFO page. It is part of CFO, not a new agent.

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

  it("is its own entry in the sidebar, right after Profit & Finance, and only that entry is highlighted on its page", () => {
    expect(NAV_GROUPS.map((g) => g.items.map((i) => i.label))).toEqual([
      ["Overview", "CEO Hub", "Action Center"],
      ["Products", "Competitors", "Profit & Finance", "Expense Tracker", "Profit Calculator", "Listings & Marketing"],
    ]);
    const items = allNavItems();
    const tracker = items.find((i) => i.id === "cfo-expenses")!;
    expect(tracker.href).toBe("/dashboard/cfo/expenses");
    expect(items.filter((i) => isActive(i, "/dashboard/cfo/expenses")).map((i) => i.id)).toEqual(["cfo-expenses"]);
    expect(items.filter((i) => isActive(i, "/dashboard/cfo")).map((i) => i.id)).toEqual(["cfo"]);
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
  const files = ["lib/expenseLedger.ts", "lib/expenseTools.ts", "app/dashboard/cfo/expenses/page.tsx", ...readdirSync(join(ROOT, "components/expenses")).filter((f) => /\.tsx$/.test(f) && !/\.test\./.test(f)).map((f) => `components/expenses/${f}`)];
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
