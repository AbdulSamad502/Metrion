import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShowcaseDashboard } from "@/components/cmo/ShowcaseDashboard";
import { createShowcaseClient, type ShowcaseClient, type ShowcaseTitle } from "@/lib/cmoShowcase";

vi.mock("next/link", () => ({ default: ({ href, children, ...r }: { href: string; children: React.ReactNode }) => <a href={href} {...r}>{children}</a> }));

const origin = { investigationId: null, turnId: null, kind: "CEO_CHAT" as const };
const title = (over: Partial<ShowcaseTitle> = {}): ShowcaseTitle => ({
  generationId: "g1", optionId: "o1", rank: 1, titleText: "Stored title <b>x</b>", charCount: 21, maxChars: 200, constraint: null, approved: null,
  sku: "S1", productLabel: "Bottle", marketplace: "AMAZON", generatedAt: "2026-10-10T00:00:00Z", origin, usage: null, ...over,
});
function fake(over: Partial<ShowcaseClient> = {}): ShowcaseClient {
  return {
    products: async () => ({ items: [{ sku: "S1", label: "Bottle", lastGeneratedAt: "2026-10-10T00:00:00Z", counts: {} }] }),
    trends: async () => ({ items: [] }),
    titles: async () => ({ items: [], usage: { available: false, basis: null, since: null } }),
    copyPacks: async () => ({ items: [] }),
    hashtags: async () => ({ items: [] }),
    compliance: async () => ({}),
    recordUsage: vi.fn(),
    ...over,
  };
}

describe("CMO showcase (read-only)", () => {
  it("shows honest empty states, the ask-the-CEO hint, and no generation controls", async () => {
    render(<ShowcaseDashboard client={fake()} />);
    expect(await screen.findByText("No news fetched yet - ask the CEO for market news")).toBeInTheDocument();
    expect(screen.getByText(/To create or change anything, ask the CEO/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask the CEO" })).toHaveAttribute("href", "/dashboard/ceo-hub");
    expect(screen.queryByRole("button", { name: /generate|regenerate|select|lock|approve/i })).toBeNull();
    expect(screen.queryByText("SAMPLE DATA", { exact: false })).toBeNull();
  });

  it("shows an error state with retry when a section fails", async () => {
    render(<ShowcaseDashboard client={fake({ trends: async () => { throw Object.assign(new Error("x"), { status: 500 }); } })} />);
    expect(await screen.findByText(/could not load this section/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
  });

  it("renders stored counts, escapes text, and shows Approved only from the saved record", async () => {
    const titles = async () => ({ items: [title({ approved: { approvalId: "a", approvedAt: "2026-10-11T00:00:00Z", editedBySeller: false } }), title({ optionId: "o2", titleText: "Other" })], usage: { available: false, basis: null, since: null } });
    render(<ShowcaseDashboard client={fake({ titles })} />);
    expect(await screen.findByText("Stored title <b>x</b>")).toBeInTheDocument();
    expect(screen.getAllByText("21 / 200 chars").length).toBe(2);
    expect(screen.getAllByText("Approved")).toHaveLength(1);
  });

  it("Frequently used says unavailable when usage is not recorded, and never invents popularity", async () => {
    const titles = async () => ({ items: [title()], usage: { available: false, basis: null, since: null } });
    render(<ShowcaseDashboard client={fake({ titles })} />);
    await screen.findByText("Stored title <b>x</b>");
    await userEvent.click(screen.getByRole("button", { name: "Frequently used" }));
    expect(await screen.findByText(/Frequently used unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("Stored title <b>x</b>")).toBeNull();
  });

  it("copy writes to the clipboard then emits a fire-and-forget COPIED event", async () => {
    const recordUsage = vi.fn();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const titles = async () => ({ items: [title()], usage: { available: false, basis: null, since: null } });
    render(<ShowcaseDashboard client={fake({ titles, recordUsage })} />);
    await screen.findByText("Stored title <b>x</b>");
    await userEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]);
    await waitFor(() => expect(recordUsage).toHaveBeenCalledWith({ generationId: "g1", optionId: "o1", resultPart: "TITLE", kind: "COPIED", surface: "DASHBOARD" }));
    expect(writeText).toHaveBeenCalledWith("Stored title <b>x</b>");
  });

  it("shows the SAMPLE DATA banner only when told it is sample", () => {
    render(<ShowcaseDashboard client={fake()} sample />);
    expect(screen.getByText(/SAMPLE DATA/)).toBeInTheDocument();
  });
});

describe("CMO showcase client and network surface", () => {
  it("GETs the showcase routes and never rejects on a failed usage event", async () => {
    const calls: { m: string; u: string }[] = [];
    const orig = globalThis.fetch;
    globalThis.fetch = (async (u: string, init?: RequestInit) => {
      calls.push({ m: init?.method ?? "GET", u: String(u) });
      if (init?.method === "POST") throw new Error("offline");
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      const c = createShowcaseClient(async () => "t");
      await c.titles({ marketplace: "AMAZON", view: "recent", q: "a b" });
      await c.products();
      c.recordUsage({ generationId: "g", kind: "VIEWED", surface: "DASHBOARD" });
      await new Promise((r) => setTimeout(r, 10));
      expect(calls[0].u).toContain("/api/v1/cmo/showcase/titles?marketplace=AMAZON&q=a+b&view=recent");
      expect(calls.filter((x) => x.m !== "GET").map((x) => x.u)).toEqual([expect.stringContaining("/cmo/showcase/usage-events")]);
    } finally { globalThis.fetch = orig; }
  });

  it("no CMO component or client calls a CMO generation POST route (AC-D1)", () => {
    const root = join(__dirname, "..", "..");
    const files = [join(root, "lib/cmoShowcase.ts"), join(root, "app/dashboard/cmo/page.tsx"), ...readdirSync(__dirname).filter((f) => /\.tsx?$/.test(f) && !f.includes(".test.")).map((f) => join(__dirname, f))];
    for (const f of files) {
      const src = readFileSync(f, "utf-8");
      expect(src, f).not.toMatch(/\/cmo\/(title-sets|listing-copy|description|bullets|keywords|backend-terms|hashtags|catalog-answers|images|image-analyses|image-hints|title-approvals|niche-terms|market-trends)/);
      expect(src, f).not.toMatch(/<(input|textarea)\b(?![^>]*type="(search|checkbox)")/);
    }
  });
});
