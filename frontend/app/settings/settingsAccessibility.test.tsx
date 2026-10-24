import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { notifications, shellData, TestShell } from "@/test-support/shellMock";

const updatePassword = vi.fn();
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: async () => "t" }),
  useUser: () => ({ isLoaded: true, user: { externalAccounts: [], passwordEnabled: true, primaryEmailAddress: { emailAddress: "a@b.co" }, updatePassword, reload: vi.fn(async () => {}) } }),
}));
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(notifications())}>{children}</TestShell>,
}));

import SettingsPage from "@/app/settings/page";

const SUB = { frequency: "WEEKLY", channel: "IN_APP", enabled: true, lastSentAt: null, isDefault: true };
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
beforeEach(() => { updatePassword.mockReset(); vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => (init?.method === "PUT" ? json({ status: "OK" }) : json(SUB)))); });
afterEach(() => vi.unstubAllGlobals());

describe("Settings accessibility (mocked Clerk and API)", () => {
  it("names the tab for what it controls, and keeps the old #notifications link working", async () => {
    window.history.replaceState(null, "", "/settings#notifications");
    render(<SettingsPage />);
    expect(await screen.findByRole("tab", { name: /Competitor digest/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Notifications" })).toBeNull();
  });

  it("the digest choice is a group of toggle buttons (aria-pressed), not a radio group, each at least 40px high, and still saves immediately with the same body", async () => {
    window.history.replaceState(null, "", "/settings#notifications");
    render(<SettingsPage />);
    const group = await screen.findByRole("group", { name: "Digest frequency" });
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    for (const name of ["Off", "Daily", "Weekly"]) {
      const b = screen.getByRole("button", { name });
      expect(group).toContainElement(b);
      expect(b.className).toContain("min-h-[40px]"); // jsdom has no layout, so the guaranteed height is checked as the class that sets it
    }
    expect(screen.getByRole("button", { name: "Weekly" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.setup().click(screen.getByRole("button", { name: "Daily" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Daily" })).toHaveAttribute("aria-pressed", "true"));
    const put = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(put[1].body as string)).toEqual({ frequency: "DAILY", channel: "IN_APP", enabled: true });
  });

  it("announces a password error as an alert and success as a status, with the same messages", async () => {
    window.history.replaceState(null, "", "/settings#account");
    render(<SettingsPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Current password"), "old-password-1");
    await user.type(screen.getByLabelText("New password"), "a-long-new-password");
    await user.type(screen.getByLabelText("Confirm password"), "something-different");
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords don't match.");
    expect(updatePassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Confirm password"));
    await user.type(screen.getByLabelText("Confirm password"), "a-long-new-password");
    updatePassword.mockResolvedValue(undefined);
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Password updated.");
    expect(updatePassword).toHaveBeenCalledWith({ newPassword: "a-long-new-password", currentPassword: "old-password-1", signOutOfOtherSessions: true });
  });

  it("uses the readable text token for the strength label and gives Show/Hide a 40px minimum", async () => {
    window.history.replaceState(null, "", "/settings#account");
    render(<SettingsPage />);
    await userEvent.setup().type(await screen.findByLabelText("New password"), "abc");
    const live = document.querySelector('[aria-live="polite"] span') as HTMLElement;
    expect(live.style.color).toBe("var(--text-6)");
    for (const b of screen.getAllByRole("button", { name: "Show password" })) {
      expect(b.className).toContain("min-h-10");
      expect(b.className).toContain("min-w-10");
      expect(b.className).not.toMatch(/min-h-9|sm:min-h-6/);
    }
  });
});
