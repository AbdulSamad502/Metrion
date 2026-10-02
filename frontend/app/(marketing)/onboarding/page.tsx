"use client";

import { useAuth, useClerk, useOrganizationList, useUser } from "@clerk/nextjs";
import { redirect, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AuthCard } from "@/components/ui/AuthCard";
import { Button } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { apiFetch, ApiError, type SessionResponse } from "@/lib/api";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** The O1/O2 blocking business-name onboarding step — the one screen Clerk doesn't
 * provide, in the same visual language as docs/design/frontend-design. Once ACTIVE it
 * hands off to /dashboard.
 *
 * Critical wrinkle: the Clerk Organization behind onboarding is created by OUR backend
 * (auth.md §6.2 — Metrion is authoritative for tenant creation, not Clerk's own UI). The
 * frontend's Clerk session has no idea that org exists until we explicitly reload the
 * user and call setActive() on it — otherwise every getToken() keeps returning a JWT
 * with no org_id, and the app looks stuck in PENDING_ONBOARDING forever even though the
 * tenant now exists server-side.
 *
 * The same gap bites *returning* users: a fresh browser session (or one that signed out
 * and back in) has no active org either, even though the user already belongs to one —
 * Clerk doesn't restore it automatically. Left alone, that meant every returning sign-in
 * hit this "let's set up your workspace" screen again. The fix: before ever showing the
 * form, check Clerk's own membership list (authoritative, not our DB) for an existing
 * org and auto-activate it — the form only renders for users who genuinely have none.
 */
export default function OnboardingPage() {
  const { isLoaded, isSignedIn, getToken } = useAuth({ treatPendingAsSignedOut: false });
  const { user } = useUser();
  const { setActive } = useClerk();
  const { isLoaded: orgsLoaded, userMemberships } = useOrganizationList({
    userMemberships: { infinite: true },
  });
  const router = useRouter();
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [businessName, setBusinessName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkingExistingOrg, setCheckingExistingOrg] = useState(true);
  const autoActivateAttempted = useRef(false);
  const guard = useSubmitGuard();

  const loadSession = async () => {
    const token = await getToken();
    try {
      const s = await apiFetch<SessionResponse>("/api/v1/session", token);
      setSession(s);
      return s;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the backend");
      return null;
    }
  };

  useEffect(() => {
    // loadSession() is async — its setState calls run in a later microtask, not
    // synchronously inside this effect body, so the cascading-render concern the
    // set-state-in-effect rule flags doesn't apply; this is a standard mount-time fetch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (isLoaded && isSignedIn) void loadSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  // Auto-activate an existing org for returning users, once per page load, before ever
  // rendering the "create workspace" form.
  useEffect(() => {
    if (!session || !orgsLoaded || autoActivateAttempted.current) return;
    if (session.onboardingState !== "PENDING_ONBOARDING") {
      // One-time derived flag from data this same effect just checked, not a sync loop.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCheckingExistingOrg(false);
      return;
    }
    autoActivateAttempted.current = true;
    const existing = userMemberships.data?.[0];
    if (!existing) {
      setCheckingExistingOrg(false);
      return;
    }
    (async () => {
      try {
        await setActive({ organization: existing.organization.id });
        await loadSession();
      } catch {
        // Fall through to the business-name form — worst case a returning user re-enters
        // their workspace name, which is harmless and recoverable, unlike a stuck spinner.
      } finally {
        setCheckingExistingOrg(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, orgsLoaded, userMemberships.data]);

  useEffect(() => {
    if (session?.onboardingState === "ACTIVE") router.replace("/dashboard");
  }, [session, router]);

  if (isLoaded && !isSignedIn) redirect("/sign-in");

  const submitBusinessName = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setSubmitting(true);
      setError(null);
      try {
        const token = await getToken();
        const result = await apiFetch<{ tenantId: string; clerkOrgId: string }>(
          "/api/v1/onboarding/business",
          token,
          { method: "POST", body: JSON.stringify({ business_name: businessName }) },
        );

        // Make the frontend's Clerk session aware of the org our backend just created.
        await user?.reload();
        await setActive({ organization: result.clerkOrgId });

        await loadSession();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Onboarding failed");
      } finally {
        setSubmitting(false);
      }
    });
  };

  const showLoading = !session || (session.onboardingState === "PENDING_ONBOARDING" && checkingExistingOrg);

  return (
    <AuthCard title="One last step" subtitle="Let's set up your workspace">
      {error && (
        <p className="mb-4 text-sm" style={{ color: "var(--negative)" }}>
          {error}
        </p>
      )}

      {showLoading && !error && <p style={{ color: "var(--text-5)" }}>Loading…</p>}

      {session?.onboardingState === "PENDING_EMAIL_VERIFICATION" && (
        <p style={{ color: "var(--text-3)" }}>Check your email to verify your address before continuing.</p>
      )}

      {session?.onboardingState === "PENDING_ONBOARDING" && !checkingExistingOrg && (
        <form onSubmit={submitBusinessName} className="flex flex-col gap-4">
          <p className="text-sm" style={{ color: "var(--text-6)" }}>
            What&apos;s your business called? This is the only detail we need to get started —
            no GSTIN or marketplace connections required.
          </p>
          <FormField
            label="Business name"
            type="text"
            required
            autoFocus
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
          />
          <Button type="submit" loading={submitting}>
            Continue
          </Button>
        </form>
      )}

      {session?.onboardingState === "ACTIVE" && <p style={{ color: "var(--text-5)" }}>Taking you in…</p>}
    </AuthCard>
  );
}
