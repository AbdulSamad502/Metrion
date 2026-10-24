import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShowcaseDashboard } from "@/components/cmo/ShowcaseDashboard";
import { ToastProvider } from "@/components/ui/Toast";
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

const deferred = <T,>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
  return { promise, resolve, reject };
};
const USAGE = { available: false, basis: null, since: null };
const page = (items: ShowcaseTitle[]) => ({ items, usage: USAGE });
const fail500 = () => Object.assign(new Error("x"), { status: 500 });

describe("CMO showcase: results stay trustworthy while loading", () => {
  it("shows the product and search the results are for", async () => {
    render(<ShowcaseDashboard client={fake()} />);
    expect(await screen.findByTestId("cmo-context")).toHaveTextContent("Showing saved results for all products.");
    await userEvent.selectOptions(await screen.findByLabelText("Filter by product"), "S1");
    expect(screen.getByTestId("cmo-context")).toHaveTextContent("Showing saved results for Bottle.");
  });

  it("does not leave Amazon titles on screen as if they were Flipkart titles", async () => {
    const flip = deferred<ReturnType<typeof page>>();
    const titles = vi.fn((f: { marketplace: string }) => (f.marketplace === "FLIPKART" ? flip.promise : Promise.resolve(page([title({ titleText: "Amazon title" })]))));
    render(<ShowcaseDashboard client={fake({ titles: titles as unknown as ShowcaseClient["titles"] })} />);
    await screen.findByText("Amazon title");
    await userEvent.click(screen.getByRole("tab", { name: "Flipkart" }));
    expect(screen.queryByText("Amazon title")).toBeNull();
    expect(screen.getByText("Loading titles…")).toBeInTheDocument();
    flip.resolve(page([title({ titleText: "Flipkart title", marketplace: "FLIPKART" })]));
    expect(await screen.findByText("Flipkart title")).toBeInTheDocument();
  });

  it("ignores an older marketplace's reply that arrives after a newer one", async () => {
    const flip = deferred<ReturnType<typeof page>>();
    const titles = vi.fn((f: { marketplace: string }) => {
      if (f.marketplace === "FLIPKART") return flip.promise; // slow
      if (f.marketplace === "MEESHO") return Promise.resolve(page([title({ titleText: "Meesho title", marketplace: "MEESHO" })]));
      return Promise.resolve(page([title({ titleText: "Amazon title" })]));
    });
    render(<ShowcaseDashboard client={fake({ titles: titles as unknown as ShowcaseClient["titles"] })} />);
    await screen.findByText("Amazon title");
    await userEvent.click(screen.getByRole("tab", { name: "Flipkart" }));
    await userEvent.click(screen.getByRole("tab", { name: "Meesho" }));
    expect(await screen.findByText("Meesho title")).toBeInTheDocument();
    flip.resolve(page([title({ titleText: "Flipkart title", marketplace: "FLIPKART" })])); // arrives last
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("Flipkart title")).toBeNull();
    expect(screen.getByText("Meesho title")).toBeInTheDocument();
  });

  it("keeps the saved results visible while Refresh re-reads them, and cannot start a second refresh", async () => {
    const slow = deferred<ReturnType<typeof page>>();
    let calls = 0;
    const titles = vi.fn(() => (++calls === 1 ? Promise.resolve(page([title({ titleText: "Saved title" })])) : slow.promise));
    render(<ShowcaseDashboard client={fake({ titles: titles as unknown as ShowcaseClient["titles"] })} />);
    await screen.findByText("Saved title");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(screen.getByTestId("cmo-context")).toHaveTextContent(/Refreshing… what is shown is the last result that loaded/);
    expect(screen.getByText("Saved title")).toBeInTheDocument();
    expect(screen.getByText("Updating titles…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refreshing…" }));
    expect(titles).toHaveBeenCalledTimes(2);
    slow.resolve(page([title({ titleText: "Newer title" })]));
    expect(await screen.findByText("Newer title")).toBeInTheDocument();
    expect(screen.queryByText("Updating titles…")).toBeNull();
  });

  it("keeps the last results and says so when a refresh fails, with a retry", async () => {
    let fail = false;
    const titles = vi.fn(async () => { if (fail) throw fail500(); return page([title({ titleText: "Saved title" })]); });
    render(<ShowcaseDashboard client={fake({ titles: titles as unknown as ShowcaseClient["titles"] })} />);
    await screen.findByText("Saved title");
    fail = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/Showing the last titles that loaded/)).toBeInTheDocument();
    expect(screen.getByText("Saved title")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() => expect(screen.queryByText(/Showing the last titles that loaded/)).toBeNull());
    expect(screen.getByText("Saved title")).toBeInTheDocument();
  });

  it("shows a skeleton, not the old error, while a failed first load is retried", async () => {
    const gate = deferred<{ items: [] }>();
    let calls = 0;
    const trends = vi.fn(() => (++calls === 1 ? Promise.reject(fail500()) : gate.promise));
    render(<ShowcaseDashboard client={fake({ trends: trends as unknown as ShowcaseClient["trends"] })} />);
    await screen.findByText(/could not load this section/i);
    await userEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]);
    expect(screen.getByText("Loading market news…")).toBeInTheDocument();
    gate.resolve({ items: [] });
    expect(await screen.findByText("No news fetched yet - ask the CEO for market news")).toBeInTheDocument();
  });

  it("states a missing limit as 'no limit stated', never as a blank or 'null'", async () => {
    render(<ShowcaseDashboard client={fake({ titles: async () => page([title({ maxChars: null })]) })} />);
    expect(await screen.findByText("21 chars · no limit stated")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/null/);
  });
});

describe("CMO showcase: copy and mark-as-used say only what happened", () => {
  const withTitle = (recordUsage: ShowcaseClient["recordUsage"]) => fake({ titles: async () => page([title()]), recordUsage });
  const openDetails = async () => {
    await screen.findByText("Stored title <b>x</b>");
    await userEvent.click(screen.getAllByRole("button", { name: "Details" })[0]);
    return screen.findByRole("dialog");
  };

  it("tells the seller when the clipboard refuses, and records nothing", async () => {
    const recordUsage = vi.fn();
    Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => { throw new Error("denied"); } }, configurable: true });
    render(<ToastProvider><ShowcaseDashboard client={withTitle(recordUsage)} /></ToastProvider>);
    await screen.findByText("Stored title <b>x</b>");
    await userEvent.click(screen.getAllByRole("button", { name: "Copy" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not copy/);
    expect(recordUsage).not.toHaveBeenCalledWith(expect.objectContaining({ kind: "COPIED" }));
  });

  it("says 'Marked as used' only after the server accepted it, and sends it once for a double press", async () => {
    const gate = deferred<boolean>();
    const recordUsage = vi.fn((e: { kind: string }) => (e.kind === "MARKED_USED" ? gate.promise : undefined));
    render(<ShowcaseDashboard client={withTitle(recordUsage as unknown as ShowcaseClient["recordUsage"])} />);
    const dialog = await openDetails();
    const btn = within(dialog).getByRole("button", { name: "Mark as used" });
    fireEvent.click(btn);
    fireEvent.click(btn);
    expect(within(dialog).getByRole("button", { name: "Recording…" })).toBeDisabled();
    expect(within(dialog).queryByText("Marked as used")).toBeNull();
    expect(recordUsage.mock.calls.filter(([e]) => e.kind === "MARKED_USED")).toHaveLength(1);
    gate.resolve(true);
    expect(await within(dialog).findByRole("button", { name: "Marked as used" })).toBeDisabled();
  });

  it("reports a refused 'mark as used' and lets the seller try again", async () => {
    const answers = [false, true];
    const recordUsage = vi.fn((e: { kind: string }) => (e.kind === "MARKED_USED" ? Promise.resolve(answers.shift()!) : undefined));
    render(<ShowcaseDashboard client={withTitle(recordUsage as unknown as ShowcaseClient["recordUsage"])} />);
    const dialog = await openDetails();
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark as used" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/Could not record that/);
    expect(within(dialog).queryByText("Marked as used")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(await within(dialog).findByRole("button", { name: "Marked as used" })).toBeInTheDocument();
  });

  it("the real client answers true only when the server accepts the event, and false (never a rejection) otherwise", async () => {
    const orig = globalThis.fetch;
    try {
      const c = createShowcaseClient(async () => "t");
      globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
      await expect(c.recordUsage({ generationId: "g", kind: "MARKED_USED", surface: "DASHBOARD" })).resolves.toBe(true);
      globalThis.fetch = (async () => new Response("{}", { status: 500 })) as typeof fetch;
      await expect(c.recordUsage({ generationId: "g", kind: "MARKED_USED", surface: "DASHBOARD" })).resolves.toBe(false);
      globalThis.fetch = (async () => { throw new Error("offline"); }) as typeof fetch;
      await expect(c.recordUsage({ generationId: "g", kind: "MARKED_USED", surface: "DASHBOARD" })).resolves.toBe(false);
    } finally { globalThis.fetch = orig; }
  });
});
