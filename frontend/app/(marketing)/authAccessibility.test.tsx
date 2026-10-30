import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// MOCKED Clerk only: these tests pin what the pages render for a given Clerk answer. They say nothing about real Clerk behaviour, which was not exercised.
const h = vi.hoisted(() => ({
  signInPassword: vi.fn(),
  signUpPassword: vi.fn(),
  verifyEmailCode: vi.fn(),
}));
vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ isLoaded: true, isSignedIn: false }),
  useClerk: () => ({ signOut: vi.fn(), client: { signIn: { authenticateWithRedirect: vi.fn() }, signUp: { authenticateWithRedirect: vi.fn() } } }),
  useSignIn: () => ({ fetchStatus: "idle", signIn: { password: h.signInPassword, status: "needs_first_factor", finalize: vi.fn() } }),
  useSignUp: () => ({
    fetchStatus: "idle",
    signUp: { password: h.signUpPassword, status: "missing_requirements", unverifiedFields: ["email_address"], verifications: { sendEmailCode: async () => ({ error: null }), verifyEmailCode: h.verifyEmailCode }, finalize: vi.fn() },
  }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

import SignInPage from "@/app/(marketing)/sign-in/page";
import SignUpPage from "@/app/(marketing)/sign-up/page";

beforeEach(() => { h.signInPassword.mockReset(); h.signUpPassword.mockReset(); h.verifyEmailCode.mockReset(); });

const clerkError = (code: string) => ({ error: { errors: [{ code }] } });

describe("Sign-in presentation (mocked Clerk)", () => {
  it("announces a sign-in error as an alert with the same message as before", async () => {
    h.signInPassword.mockResolvedValue(clerkError("form_password_incorrect"));
    render(<SignInPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email address"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/password/i);
  });

  it("names the real Settings tab in the Google-account message, and announces it", async () => {
    h.signInPassword.mockResolvedValue(clerkError("strategy_for_user_invalid"));
    render(<SignInPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email address"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "whatever-123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Settings → Account & security");
    expect(alert).not.toHaveTextContent("Settings → Security");
  });

  it("gives 'Forgot password?' and the footer sign-up link a 40px minimum height without changing where they go", () => {
    render(<SignInPage />);
    const forgot = screen.getByRole("link", { name: "Forgot password?" });
    const signUp = screen.getByRole("link", { name: "Sign up" });
    expect(forgot).toHaveAttribute("href", "/forgot-password");
    expect(signUp).toHaveAttribute("href", "/sign-up");
    for (const l of [forgot, signUp]) expect(l.className).toContain("min-h-10"); // jsdom has no layout: the class that sets the height is checked; real heights were measured in Chromium
  });
});

describe("Sign-up presentation (mocked Clerk)", () => {
  it("announces 'account exists' and a generic error as alerts", async () => {
    h.signUpPassword.mockResolvedValueOnce(clerkError("form_identifier_exists"));
    render(<SignUpPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email address"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("An account with this email already exists.");
    expect(screen.getByRole("link", { name: "Sign in instead" })).toHaveAttribute("href", "/sign-in");
  });

  it("announces a verification-code error, and the Resend button is at least 40px tall", async () => {
    h.signUpPassword.mockResolvedValue({ error: null });
    h.verifyEmailCode.mockResolvedValue(clerkError("form_code_incorrect"));
    render(<SignUpPage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email address"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "a-long-password-1");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await user.type(await screen.findByLabelText("Verification code"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resend code/ }).className).toContain("min-h-10");
  });

  it("uses the readable text token for the password rule and the strength label, and a 40px footer link", async () => {
    render(<SignUpPage />);
    await userEvent.setup().type(screen.getByLabelText("Password"), "abc");
    const rule = screen.getByText(/At least 10 characters/);
    expect(rule.style.color).toBe("var(--text-6)");
    const label = document.querySelector('[aria-live="polite"] span') as HTMLElement;
    expect(label.style.color).toBe("var(--text-6)");
    expect(screen.getByRole("link", { name: "Sign in" }).className).toContain("min-h-10");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull()); // nothing is announced before anything goes wrong
  });
});
