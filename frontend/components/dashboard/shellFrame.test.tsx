import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/dashboard/pi";
const getToken = async () => "t"; // Clerk's getToken is stable; a fresh one per render would refetch forever
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken }),
  useUser: () => ({ user: { fullName: "Asha Rao", primaryEmailAddress: { emailAddress: "a@example.com" } } }),
  useClerk: () => ({ signOut: vi.fn() }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/image", () => ({ default: (p: { alt: string }) => <span role="img" aria-label={p.alt} /> }));

import { AppFrame, isAppPath } from "@/components/dashboard/AppFrame";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ShellFrame } from "@/components/dashboard/ShellFrame";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const calls = (needle: string) => (fetch as unknown as { mock: { calls: [string][] } }).mock.calls.filter((c) => String(c[0]).includes(needle)).length;

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  pathname = "/dashboard/pi";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/api/v1/session")) return json({ appUserId: "u", emailVerified: true, tenantId: "t", membershipStatus: "ACTIVE", role: "OWNER", onboardingState: "ACTIVE" });
    if (url.includes("/ci/alerts")) return json({ alerts: [] });
    if (url.includes("/cfo/data-requests")) return json([]);
    return json({});
  }));
});
afterEach(() => {
  cleanup(); // unmount first: a late state update must not run an effect after the globals it uses (ResizeObserver) have been removed
  vi.unstubAllGlobals();
});

const page = (name: string) => (
  <DashboardShell title={`Page ${name}`} subtitle="">
    <p>body {name}</p>
  </DashboardShell>
);

describe("the signed-in frame stays mounted while the seller navigates", () => {
  it("keeps the sidebar, shows no full-screen loading and does not re-fetch the session", async () => {
    const { rerender } = render(<ShellFrame>{page("A")}</ShellFrame>);
    await screen.findByText("body A");
    const sidebar = screen.getByLabelText("Primary");
    expect(calls("/api/v1/session")).toBe(1);

    pathname = "/dashboard/cfo";
    rerender(<ShellFrame>{page("B")}</ShellFrame>); // a client-side navigation: the layout stays, the page changes

    expect(screen.getByText("body B")).toBeInTheDocument(); // the next page is there at once, not after a session round-trip
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // no full-screen "Loading…" replacing the app
    expect(screen.getByLabelText("Primary")).toBe(sidebar); // the very same sidebar element: nothing was torn down
    expect(calls("/api/v1/session")).toBe(1);
  });

  it("still refreshes the notification feeds on each navigation, without blanking what is shown", async () => {
    const { rerender } = render(<ShellFrame>{page("A")}</ShellFrame>);
    await screen.findByText("body A");
    await waitFor(() => expect(calls("/ci/alerts")).toBe(1));
    pathname = "/dashboard/cfo";
    rerender(<ShellFrame>{page("B")}</ShellFrame>);
    await waitFor(() => expect(calls("/ci/alerts")).toBe(2));
    expect(calls("/cfo/data-requests")).toBe(2);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("closes the mobile navigation drawer when the page changes (it used to close only because the whole frame remounted)", async () => {
    const { rerender } = render(<ShellFrame>{page("A")}</ShellFrame>);
    await screen.findByText("body A");
    const drawer = screen.getByLabelText("Primary");
    expect(drawer.className).toContain("invisible"); // closed on small screens
    await userEvent.setup().click(screen.getByRole("button", { name: "Open navigation" }));
    expect(drawer.className).not.toContain("invisible");

    pathname = "/dashboard/cfo";
    rerender(<ShellFrame>{page("B")}</ShellFrame>);
    expect(screen.getByLabelText("Primary").className).toContain("invisible");
  });

  it("makes a page's own requests available immediately after navigation", async () => {
    const { rerender } = render(<ShellFrame>{page("A")}</ShellFrame>);
    await screen.findByText("body A");
    const before = calls("/api/v1/session");
    pathname = "/dashboard/cmo";
    await act(async () => rerender(<ShellFrame>{page("B")}</ShellFrame>));
    expect(calls("/api/v1/session")).toBe(before);
  });
});

describe("a page used without a layout (Settings, tests) still gets its own frame", () => {
  it("loads the session once and renders the header, navigation and body", async () => {
    render(page("Solo"));
    expect(await screen.findByText("body Solo")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Page Solo" })).toBeInTheDocument();
    expect(screen.getByLabelText("Primary")).toBeInTheDocument();
    expect(calls("/api/v1/session")).toBe(1);
  });
});

describe("Settings and the dashboard share one frame", () => {
  it("recognises the signed-in routes and leaves marketing and auth pages alone", () => {
    for (const p of ["/dashboard", "/dashboard/pi", "/settings", "/settings/anything"]) expect(isAppPath(p)).toBe(true);
    for (const p of ["/", "/sign-in", "/onboarding", "/dashboardx", "/settings-old", null]) expect(isAppPath(p)).toBe(false);
  });

  it("does not wrap, fetch a session for, or show a sidebar on a marketing page", async () => {
    pathname = "/sign-in";
    render(<AppFrame><p>marketing</p></AppFrame>);
    expect(screen.getByText("marketing")).toBeInTheDocument();
    expect(screen.queryByLabelText("Primary")).not.toBeInTheDocument();
    expect(calls("/api/v1/session")).toBe(0);
  });

  it("crossing between Settings and a dashboard page, both ways, keeps the frame, the session, and the keyboard focus", async () => {
    pathname = "/dashboard/pi";
    const { rerender } = render(<AppFrame>{page("Products")}</AppFrame>);
    await screen.findByText("body Products");
    const sidebar = screen.getByLabelText("Primary");
    const link = screen.getByRole("link", { name: /Settings/ });
    link.focus(); // the seller tabbed to the Settings link and pressed Enter
    expect(link).toHaveFocus();
    await waitFor(() => expect(calls("/ci/alerts")).toBe(1)); // the first read has finished: a navigation made while one is running is folded into a single follow-up read (see useNotifications)

    pathname = "/settings"; // dashboard -> settings
    rerender(<AppFrame>{page("Settings")}</AppFrame>);
    expect(screen.getByText("body Settings")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // before: a full-screen "Loading…"
    expect(screen.getByLabelText("Primary")).toBe(sidebar); // before: a new sidebar element
    expect(link).toHaveFocus(); // before: focus fell to <body>

    await waitFor(() => expect(calls("/ci/alerts")).toBe(2));

    pathname = "/dashboard/cfo"; // settings -> dashboard
    rerender(<AppFrame>{page("CFO")}</AppFrame>);
    expect(screen.getByText("body CFO")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Primary")).toBe(sidebar);
    expect(calls("/api/v1/session")).toBe(1); // one session for the whole visit
    await waitFor(() => expect(calls("/ci/alerts")).toBe(3)); // the feeds still refresh on each navigation, in the background
  });

  it("never doubles the frame when a layout and the root both ask for one", async () => {
    pathname = "/dashboard/pi";
    render(<AppFrame><ShellFrame>{page("Nested")}</ShellFrame></AppFrame>);
    await screen.findByText("body Nested");
    expect(screen.getAllByLabelText("Primary")).toHaveLength(1);
    expect(calls("/api/v1/session")).toBe(1);
  });
});

describe("orientation: where am I, and where can I go", () => {
  it("names the page in the browser tab, and keeps the name current as the page changes", async () => {
    pathname = "/dashboard/pi";
    const { rerender } = render(<ShellFrame>{page("Products")}</ShellFrame>);
    await screen.findByText("body Products");
    expect(document.title).toBe("Page Products · Metrion"); // before: every page was just "Metrion"
    rerender(<ShellFrame>{page("CFO")}</ShellFrame>);
    expect(document.title).toBe("Page CFO · Metrion");
  });

  it("groups the menu as Start, Business and System, and marks exactly the current page", async () => {
    pathname = "/dashboard/cfo";
    render(<ShellFrame>{page("Finance")}</ShellFrame>);
    await screen.findByText("body Finance");
    const nav = screen.getByLabelText("Sections");
    for (const heading of ["Start", "Business", "System"]) expect(within(nav).getByText(heading)).toBeInTheDocument();
    const labels = within(nav).getAllByRole("link").map((l) => l.textContent?.trim());
    expect(labels).toEqual(["Overview", "CEO Hub", "Action Center", "Products", "Competitors", "Profit & Finance", "Profit Calculator", "Listings & Marketing", "Agents", "Settings"]);
    const current = within(nav).getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Profit & Finance");
  });
});
