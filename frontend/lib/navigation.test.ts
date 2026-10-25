import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { FOOTER_NAV, NAV_GROUPS, PAGE_COPY, SYSTEM_GROUP_LABEL, allNavItems, isActive, pageTitle } from "@/lib/navigation";

describe("navigation (customer-goal groups)", () => {
  it("groups by what the seller wants to do, and Ask Metrion is one click from anywhere", () => {
    expect(NAV_GROUPS.map((g) => g.label)).toEqual(["Start", "Agents", "Tools"]);
    expect(SYSTEM_GROUP_LABEL).toBe("System");
    expect(NAV_GROUPS[1].items.map((i) => i.label)).toEqual(["Products", "Competitors", "Profit & Finance", "Listings & Marketing"]);
    expect(NAV_GROUPS[2].items.map((i) => i.label)).toEqual(["Profit Calculator", "Expense Tracker"]);
    expect(FOOTER_NAV.map((i) => i.label)).toEqual(["Agents", "Settings"]);
    expect(NAV_GROUPS[0].items.map((i) => i.label)).toEqual(["Overview", "CEO Hub", "Action Center"]);
  });
  it("keeps every real route reachable and lists no inert 'Soon' entry", () => {
    const hrefs = allNavItems().map((i) => i.href);
    for (const h of ["/dashboard", "/dashboard/ceo-hub", "/dashboard/notifications", "/dashboard/cfo", "/dashboard/pi", "/dashboard/competitors", "/dashboard/cmo", "/dashboard/agents", "/dashboard/pnl-calculator", "/dashboard/expense-tracker", "/settings"]) {
      expect(hrefs).toContain(h);
    }
    expect(allNavItems().every((i) => !i.soon && i.href)).toBe(true);
    expect(FOOTER_NAV.map((i) => i.id)).not.toContain("cart");
  });
  it("highlights Overview only on its own page", () => {
    const overview = allNavItems().find((i) => i.id === "overview")!;
    expect(isActive(overview, "/dashboard")).toBe(true);
    expect(isActive(overview, "/dashboard/cfo")).toBe(false);
  });

  it("calls every page by the same name in the menu and in its heading, with no internal role name in either", () => {
    for (const item of allNavItems()) expect(item.label).toBe(PAGE_COPY[item.id as keyof typeof PAGE_COPY].title);
    for (const { title } of Object.values(PAGE_COPY)) expect(title).not.toMatch(/(CEO|CFO|CMO|PI|CI)/);
  });

  it("makes each page take its title and description from PAGE_COPY instead of its own wording", () => {
    const pages: Record<string, string> = {
      overview: "app/dashboard/page.tsx", "ceo-hub": "app/dashboard/ceo-hub/page.tsx", notifications: "app/dashboard/notifications/page.tsx",
      products: "app/dashboard/pi/page.tsx", competitors: "app/dashboard/competitors/page.tsx", cfo: "app/dashboard/cfo/page.tsx",
      cmo: "app/dashboard/cmo/page.tsx", agents: "app/dashboard/agents/page.tsx", settings: "app/settings/page.tsx",
    };
    for (const [id, file] of Object.entries(pages)) {
      const src = readFileSync(join(process.cwd(), file), "utf8");
      expect(src, file).toContain(`PAGE_COPY["${id}"]`);
      expect(src, file).not.toMatch(/<DashboardShell[^>]*title="/); // no hand-written heading
    }
  });
});

describe("every page has a route-level title", () => {
  it("exports metadata for each page that matches its heading, so the tab and the route announcement name it", async () => {
    const layouts: Record<string, () => Promise<{ metadata: { title: string } }>> = {
      overview: () => import("@/app/dashboard/layout"), "ceo-hub": () => import("@/app/dashboard/ceo-hub/layout"),
      notifications: () => import("@/app/dashboard/notifications/layout"), products: () => import("@/app/dashboard/pi/layout"),
      competitors: () => import("@/app/dashboard/competitors/layout"), cfo: () => import("@/app/dashboard/cfo/layout"),
      cmo: () => import("@/app/dashboard/cmo/layout"), agents: () => import("@/app/dashboard/agents/layout"), settings: () => import("@/app/settings/layout"),
    };
    for (const [id, load] of Object.entries(layouts)) expect((await load()).metadata.title).toBe(pageTitle(id as keyof typeof PAGE_COPY));
  });
});
