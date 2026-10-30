import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

// MOCKED Clerk and API only. Real Clerk and a real backend were not exercised.
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: true, getToken: async () => "t" }),
  useUser: () => ({ user: { reload: vi.fn() } }),
  useClerk: () => ({ setActive: vi.fn() }),
  useOrganizationList: () => ({ isLoaded: true, userMemberships: { data: [] } }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), redirect: vi.fn() }));
vi.mock("@/components/profile/BusinessProfileSteps", () => ({ BusinessProfileSteps: () => null }));

import OnboardingPage from "@/app/(marketing)/onboarding/page";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const SESSION = { appUserId: "u", emailVerified: true, tenantId: null, membershipStatus: null, role: null, onboardingState: "PENDING_ONBOARDING", profileComplete: false };
afterEach(() => vi.unstubAllGlobals());

describe("Onboarding loading and errors (mocked Clerk and API)", () => {
  it("announces loading as a status while the session is being read", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<OnboardingPage />);
    expect(await screen.findByRole("status")).toHaveTextContent("Loading…");
  });

  it("announces a failed session load as an alert and 'Try again' re-reads the same session endpoint, nothing else", async () => {
    const f = vi.fn();
    f.mockResolvedValueOnce(json("down", 503)).mockResolvedValue(json(SESSION));
    vi.stubGlobal("fetch", f);
    render(<OnboardingPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByLabelText("Business name")).toBeInTheDocument()); // the workspace form appears once the session loads
    expect(screen.queryByRole("alert")).toBeNull();
    const urls = f.mock.calls.map((c) => String(c[0]));
    expect(urls).toHaveLength(2);
    expect(urls.every((u) => u.endsWith("/api/v1/session"))).toBe(true);
  });

  it("does not offer 'Try again' when the session did load (a failed workspace save keeps its own behaviour)", async () => {
    const f = vi.fn();
    f.mockResolvedValueOnce(json(SESSION)).mockResolvedValue(json("boom", 500));
    vi.stubGlobal("fetch", f);
    render(<OnboardingPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Business name"), "Asha Home Goods");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
