import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const snapshot = { id: "s1", capturedAt: "2026-10-10T10:00:00Z", isStale: false, captureStatus: "CONFIRMED", confidence: "VERIFIED", title: "Rival jar", listedPricePaise: 49900, visibleDiscountPaise: null, availability: "IN_STOCK", variantKey: null };

let snapshotCalls: number;
let snapshotsAnswer: () => Promise<Response>;

beforeEach(() => {
  snapshotCalls = 0;
  snapshotsAnswer = async () => reply([snapshot]);
  window.history.replaceState(null, "", "/dashboard/competitors");
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    if (path === "/api/v1/ci/competitor-urls") return reply([{ id: "u1", marketplace: "AMAZON", url: "https://amazon.in/dp/B0TEST", label: "Rival jar", linkedSku: null, status: "ACTIVE", tags: [], createdAt: "2026-10-01T00:00:00Z" }]);
    if (path.endsWith("/u1/snapshots")) { snapshotCalls++; return snapshotsAnswer(); }
    if (path.endsWith("/u1/price-events")) return reply([]);
    if (path.endsWith("/u1/listing-diff")) return reply({ available: false, reason: "only one snapshot" });
    return reply({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function openDetail() {
  render(<CompetitorWorkspace />);
  const user = userEvent.setup();
  const select = await screen.findByRole("combobox");
  await waitFor(() => expect(screen.getByRole("option", { name: "Rival jar" })).toBeInTheDocument());
  await user.selectOptions(select, "u1");
  await screen.findByText("Competitor Detail — Rival jar");
  await waitFor(() => expect(snapshotCalls).toBe(1));
  return user;
}

describe("Competitor detail: Refresh", () => {
  it("re-reads the history, shows that it is working, then says when it was updated and with what", async () => {
    const user = await openDetail();
    let finish!: (r: Response) => void;
    snapshotsAnswer = () => new Promise((res) => { finish = res; });
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    const busy = await screen.findByRole("button", { name: "Refreshing…" });
    expect(busy).toBeDisabled();
    expect(snapshotCalls).toBe(2);
    finish(reply([snapshot, { ...snapshot, id: "s2" }]));
    expect(await screen.findByRole("status")).toHaveTextContent(/Updated .* · 2 snapshot\(s\), 0 price event\(s\)/);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("a failed refresh is announced with a retry, and does not say it was updated", async () => {
    const user = await openDetail();
    snapshotsAnswer = async () => reply("down", 503);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not set up on the server/i);
    expect(screen.queryByText(/^Updated /)).toBeNull();
    snapshotsAnswer = async () => reply([snapshot]);
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(await screen.findByRole("status")).toHaveTextContent(/Updated /);
  });
});

describe("Competitor detail: price events", () => {
  const event = (over: object) => ({ id: "e1", deltaPaise: 0, deltaPct: "0.00", direction: "DECREASE", availabilityChange: null, thresholdBreached: false, alertEligible: false, createdAt: "2026-10-10T10:00:00Z", ...over });

  async function withEvents(events: object[]) {
    const original = fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => (String(url).endsWith("/u1/price-events") ? reply(events) : original(url, init))));
    return openDetail();
  }

  it("shows an availability-only change as a stock transition, never as a zero-value price drop", async () => {
    await withEvents([event({ availabilityChange: "IN_TO_OUT" })]);
    expect(await screen.findByText(/Availability: IN STOCK → OUT OF STOCK \(price unchanged\)/)).toBeInTheDocument();
    expect(screen.queryByText(/DECREASE 0\.00%/)).toBeNull();
  });

  it("shows the reverse transition, and a price move with an availability change shows both", async () => {
    await withEvents([event({ id: "e2", availabilityChange: "OUT_TO_IN" }), event({ id: "e3", direction: "DECREASE", deltaPaise: -5000, deltaPct: "10.00", availabilityChange: "IN_TO_OUT" })]);
    expect(await screen.findByText(/Availability: OUT OF STOCK → IN STOCK/)).toBeInTheDocument();
    expect(screen.getByText(/DECREASE 10\.00% \(₹50\.00\)/)).toBeInTheDocument();
    expect(screen.getByText(/· IN STOCK → OUT OF STOCK/)).toBeInTheDocument();
  });

  it("a plain price change is unchanged", async () => {
    await withEvents([event({ direction: "INCREASE", deltaPaise: 2500, deltaPct: "5.00" })]);
    expect(await screen.findByText(/INCREASE 5\.00% \(₹25\.00\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Availability:/)).toBeNull();
  });
});

describe("Competitor detail: compare against your product", () => {
  it("tells the seller what to do when Metrion has no such product, instead of echoing the raw error", async () => {
    const original = fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => (String(url).includes("/comparison") ? reply("No SellerProduct for 'TEST-SKU-001' — no matching sales_line row.", 404) : original(url, init))));
    const user = await openDetail();
    await user.type(screen.getByPlaceholderText("Your product's SKU / marketplace item id"), "TEST-SKU-001");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no product "TEST-SKU-001" yet.*Save it in the Seller Product form/);
    expect(screen.queryByText(/sales_line/)).toBeNull();
  });
});
