import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { notifications, shellData, TestShell } from "@/test-support/shellMock";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "t" }),
  useUser: () => ({ isLoaded: true, user: { externalAccounts: [], passwordEnabled: true, primaryEmailAddress: { emailAddress: "a@b.co" }, updatePassword: vi.fn(), reload: vi.fn() } }),
}));
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(notifications())}>{children}</TestShell>,
}));

import SettingsPage from "@/app/settings/page";

const SUB = { frequency: "DAILY", channel: "EMAIL", enabled: true, isDefault: false };
type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const stub = (h: Handler) => { const f = vi.fn(async (url: string, init?: RequestInit) => h(url, init)); vi.stubGlobal("fetch", f); return f; };

beforeEach(() => window.history.replaceState(null, "", "/settings#notifications"));
afterEach(() => vi.unstubAllGlobals());

describe("Settings: business details", () => {
  it("the Business details button opens the form pre-filled, and Cancel closes it", async () => {
    window.history.replaceState(null, "", "/settings#business");
    const profile = { businessName: "Asha Home Goods", description: "We sell steel kitchen storage to families.", categories: "Kitchen storage", marketplaces: ["AMAZON"], priceSegment: "BUDGET", targetCustomer: "Families", businessStage: "GROWING", state: "Goa", updatedAt: "2026-10-20T10:00:00+00:00" };
    stub(() => json({ profile, complete: true, suggestedName: null }));
    render(<SettingsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Business details" }));
    const dialog = await screen.findByRole("dialog", { name: "Business details" });
    await waitFor(() => expect(screen.getByLabelText("What is your business called?")).toHaveValue("Asha Home Goods"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(dialog).not.toBeInTheDocument();
  });
});

describe("Settings: competitor digest preference", () => {
  it("shows plain wording and a working Retry when the preference cannot be loaded", async () => {
    let calls = 0;
    stub(() => (++calls === 1 ? json({ code: "X", trace: "at /srv/a.py:1" }, 503) : json(SUB)));
    render(<SettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not set up on the server yet/i);
    expect(screen.queryByText(/a\.py|"code"/)).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("radio", { name: "Daily" })).toHaveAttribute("aria-checked", "true");
  });

  it("explains a forbidden role without an error", async () => {
    stub(() => json("forbidden", 403));
    render(<SettingsPage />);
    expect(await screen.findByText(/does not have access to Competitor Intelligence/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("saves the chosen frequency with the right body and confirms it", async () => {
    const f = stub((url, init) => (init?.method === "PUT" ? json({}) : json(SUB)));
    render(<SettingsPage />);
    await userEvent.setup().click(await screen.findByRole("radio", { name: "Weekly" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: "Weekly" })).toHaveAttribute("aria-checked", "true"));
    const put = f.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(put[1]!.body))).toEqual({ frequency: "WEEKLY", channel: "EMAIL", enabled: true });
    expect(screen.getByText("Saved.")).toBeInTheDocument();
  });

  it("a failed save is announced, keeps the old choice selected and never says Saved", async () => {
    stub((url, init) => (init?.method === "PUT" ? json("nope", 403) : json(SUB)));
    render(<SettingsPage />);
    await userEvent.setup().click(await screen.findByRole("radio", { name: "Off" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
    expect(screen.getByRole("radio", { name: "Daily" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText("Saved.")).toBeNull();
  });
});
