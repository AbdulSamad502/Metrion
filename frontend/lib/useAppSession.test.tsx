import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const getToken = async () => "t";
let signedIn = true;
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: signedIn, getToken }),
  useUser: () => ({ user: { fullName: "Asha Rao", primaryEmailAddress: { emailAddress: "a@example.com" } } }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { useAppSession } from "@/lib/useAppSession";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  signedIn = true;
});

describe("useAppSession", () => {
  it("resolves the session and role label for an active workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ onboardingState: "ACTIVE", role: "OWNER" })));
    const { result } = renderHook(() => useAppSession());
    await waitFor(() => expect(result.current.session).not.toBeNull());
    expect(result.current.roleLabel).toBe("Owner");
    expect(result.current.displayName).toBe("Asha Rao");
    expect(replace).not.toHaveBeenCalled();
  });

  it("sends a workspace that is not active yet to onboarding, and a signed-out visitor to sign-in", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ onboardingState: "PENDING", role: "OWNER" })));
    renderHook(() => useAppSession());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
    replace.mockReset();
    signedIn = false;
    renderHook(() => useAppSession());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in"));
  });

  it("explains a failure in plain words instead of the raw backend message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ code: "PI_NOT_CONFIGURED" }, 503)));
    const { result } = renderHook(() => useAppSession());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toMatch(/not set up on the server yet/);
    expect(result.current.error).not.toMatch(/PI_NOT_CONFIGURED|\{/);
  });

  it("does nothing when the reply arrives after the page is gone", async () => {
    let release: (r: Response) => void = () => undefined;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((res) => { release = res; })));
    const { unmount } = renderHook(() => useAppSession());
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    unmount();
    release(reply({ onboardingState: "PENDING", role: "OWNER" }));
    await new Promise((r) => setTimeout(r, 30));
    expect(replace).not.toHaveBeenCalled(); // a late reply must not navigate a page that is no longer there
  });
});
