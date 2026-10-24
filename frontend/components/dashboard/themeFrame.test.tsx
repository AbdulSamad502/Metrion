import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/dashboard/cfo";
const getToken = async () => "t";
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken }),
  useUser: () => ({ user: { fullName: "Asha Rao", primaryEmailAddress: { emailAddress: "a@example.com" } } }),
  useClerk: () => ({ signOut: vi.fn() }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/image", () => ({ default: (p: { alt: string; src: string; className?: string }) => <span role="img" aria-label={p.alt} data-src={p.src} className={p.className} /> }));

import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ShellFrame } from "@/components/dashboard/ShellFrame";
import { resetThemeForTests, setTheme } from "@/lib/theme";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const html = () => document.documentElement.dataset.theme;
const page = () => (
  <DashboardShell title="Page" subtitle="">
    <p>body</p>
  </DashboardShell>
);

beforeEach(() => {
  window.localStorage.clear();
  resetThemeForTests();
  pathname = "/dashboard/cfo";
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/api/v1/session")) return json({ appUserId: "u", emailVerified: true, tenantId: "t", membershipStatus: "ACTIVE", role: "OWNER", onboardingState: "ACTIVE", profileComplete: true });
    if (url.includes("/ci/alerts")) return json({ alerts: [] });
    return json([]);
  }));
});
afterEach(() => {
  cleanup(); // unmount first: a late state update must not run an effect after the globals it uses (ResizeObserver) have been removed
  vi.unstubAllGlobals();
});

describe("theme in the signed-in frame", () => {
  it("is dark by default, and the toggle switches to light and back, reporting its state", async () => {
    render(<ShellFrame>{page()}</ShellFrame>);
    await screen.findByText("body");
    expect(html()).toBe("dark");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(html()).toBe("light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(html()).toBe("dark");
  });

  it("keeps the CEO Hub dark even when light is chosen", async () => {
    setTheme("light");
    pathname = "/dashboard/ceo-hub";
    render(<ShellFrame>{page()}</ShellFrame>);
    await screen.findByText("body");
    expect(html()).toBe("dark");
  });

  it("leaves no theme behind when the signed-in app unmounts (marketing and sign-in stay dark)", async () => {
    setTheme("light");
    const { unmount } = render(<ShellFrame>{page()}</ShellFrame>);
    await screen.findByText("body");
    expect(html()).toBe("light");
    unmount();
    expect(html()).toBeUndefined();
  });

  it("carries both brand marks in the sidebar, the transparent light one for CSS to pick on a light surface", async () => {
    render(<ShellFrame>{page()}</ShellFrame>);
    await screen.findByText("body");
    const marks = screen.getAllByRole("img", { name: "Metrion", hidden: true }).filter((m) => m.getAttribute("data-src")?.includes("metrion-mark"));
    expect(marks.map((m) => m.getAttribute("data-src")).sort()).toEqual(["/metrion-mark-light.png", "/metrion-mark.png"]);
    expect(marks.find((m) => m.getAttribute("data-src") === "/metrion-mark.png")).toHaveClass("mt-brand-mark--dark");
    expect(marks.find((m) => m.getAttribute("data-src") === "/metrion-mark-light.png")).toHaveClass("mt-brand-mark--light");
  });
});
