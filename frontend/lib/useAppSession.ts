"use client";

import { useAuth, useUser } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch, ApiError, type SessionResponse } from "@/lib/api";

/** Shared gate for every page in the signed-in app shell: redirects to /sign-in if
 * unauthenticated, to /onboarding if not yet ACTIVE, and otherwise resolves the session +
 * display name/role once. Used by /dashboard and /settings so the redirect rules live in
 * exactly one place. */
export function useAppSession() {
  const { isLoaded, isSignedIn, getToken } = useAuth({ treatPendingAsSignedOut: false });
  const { user } = useUser();
  const router = useRouter();
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      router.replace("/sign-in");
      return;
    }
    (async () => {
      try {
        const token = await getToken();
        const s = await apiFetch<SessionResponse>("/api/v1/session", token);
        if (s.onboardingState !== "ACTIVE") {
          router.replace("/onboarding");
          return;
        }
        setSession(s);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not reach the backend");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, isSignedIn]);

  const displayName = user?.fullName || user?.primaryEmailAddress?.emailAddress || "You";
  const roleLabel = session?.role === "OWNER" ? "Owner" : session?.role === "PARTNER" ? "Partner" : "Member";

  return { session, error, user, displayName, roleLabel };
}
