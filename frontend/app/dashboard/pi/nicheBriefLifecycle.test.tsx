import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import PiPage from "@/app/dashboard/pi/page";

const BRIEF = "22222222-2222-2222-2222-222222222222";
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });

type Brief = { id: string; tenant_id: string; status: string; category_text: string | null; budget_paise: number | null; target_price_min_paise: null; target_price_max_paise: null; marketplaces: string[] | null; constraints: null; created_by: string; created_at: string; readied_at: string | null };
let brief: Brief;
let calls: { method: string; path: string; body: unknown }[];

beforeEach(() => {
  calls = [];
  brief = { id: BRIEF, tenant_id: "t", status: "DRAFT", category_text: "jars", budget_paise: null, target_price_min_paise: null, target_price_max_paise: null, marketplaces: null, constraints: null, created_by: "u", created_at: "2026-10-01T00:00:00Z", readied_at: null };
  window.history.replaceState(null, "", "/dashboard/pi");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body });
    if (method === "POST" && path === "/api/v1/pi/niche-briefs") return reply({ nicheBriefId: BRIEF });
    if (method === "PUT") { brief = { ...brief, budget_paise: body.budget_paise ?? brief.budget_paise, marketplaces: body.marketplaces ?? brief.marketplaces }; return reply({ nicheBriefId: BRIEF }); }
    if (path.endsWith("/mark-ready")) {
      if (brief.budget_paise === null || !brief.marketplaces) return reply("niche_brief cannot transition to READY - missing required field(s): budget_paise", 400);
      brief = { ...brief, status: "READY" };
      return reply({ nicheBriefId: BRIEF, status: "READY" });
    }
    if (method === "GET" && path === `/api/v1/pi/niche-briefs/${BRIEF}`) return reply(brief);
    return reply("unexpected", 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function openBrief() {
  const user = userEvent.setup();
  render(<PiPage />);
  await user.type(screen.getByLabelText("Niche brief id to look up"), BRIEF);
  await user.click(screen.getByRole("button", { name: "Load" }));
  await screen.findByText(/status DRAFT/);
  return user;
}

describe("niche brief: creating a draft", () => {
  it("sends rupees typed with a symbol or commas as exact paise", async () => {
    const user = userEvent.setup();
    render(<PiPage />);
    await user.type(screen.getByPlaceholderText("e.g. 50000"), "₹50,000.5");
    await user.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ budget_paise: 5000050 });
  });

  it("refuses a budget it cannot read instead of silently dropping it, and sends nothing", async () => {
    const user = userEvent.setup();
    render(<PiPage />);
    await user.type(screen.getByPlaceholderText("e.g. 50000"), "about fifty thousand");
    await user.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/budget must be an amount in rupees/);
    expect(calls).toHaveLength(0);
  });
});

describe("niche brief: DRAFT -> READY", () => {
  it("says what the draft still needs, and Mark READY on an incomplete draft shows the backend's reason and changes nothing", async () => {
    const user = await openBrief();
    expect(screen.getByTestId("brief-needs")).toHaveTextContent("a budget, at least one marketplace");
    await user.click(screen.getByRole("button", { name: "Mark READY" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/missing required field\(s\): budget_paise/);
    expect(screen.getByText(/status DRAFT/)).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("completes the missing details through PUT, then Mark READY changes the status shown, with a confirmation", async () => {
    const user = await openBrief();
    await user.type(within(screen.getByTestId("brief-needs")).getByPlaceholderText("e.g. 50000"), "50000");
    await user.click(within(screen.getByTestId("brief-needs")).getByRole("checkbox", { name: "AMAZON" }));
    await user.click(screen.getByRole("button", { name: "Save missing details" }));
    await waitFor(() => expect(screen.queryByTestId("brief-needs")).toBeNull());
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ category_text: null, budget_paise: 5000000, marketplaces: ["AMAZON"] });
    await user.click(screen.getByRole("button", { name: "Mark READY" }));
    expect(await screen.findByText(/status READY/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Status is now READY.");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
