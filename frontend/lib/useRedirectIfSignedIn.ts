"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Sign-in/sign-up pages are only for signed-out visitors. A browser that already holds a
 * live Clerk session makes every sign-in/sign-up call fail with `session_exists` ("You're
 * already signed in") — so instead of letting the seller hit that dead end, send them on to
 * /onboarding, which activates their org and hands off to /dashboard. */
export function useRedirectIfSignedIn(to = "/onboarding") {
  const { isLoaded, isSignedIn } = useAuth({ treatPendingAsSignedOut: false });
  const router = useRouter();
  useEffect(() => {
    if (isLoaded && isSignedIn) router.replace(to);
  }, [isLoaded, isSignedIn, router, to]);
}
