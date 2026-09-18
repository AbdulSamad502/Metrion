"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Keeps a signed-in visitor from being "forced back through" the marketing page: as soon
 * as Clerk resolves a session, redirect straight to /dashboard (which itself sends anyone
 * not yet ACTIVE on to /onboarding via useAppSession — this doesn't duplicate that logic,
 * just gets out of the way of it). Signed-out and still-loading visitors see the landing
 * page normally; loading renders nothing rather than a flash of marketing content. */
export function LandingGate({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoaded && isSignedIn) router.replace("/dashboard");
  }, [isLoaded, isSignedIn, router]);

  if (!isLoaded || isSignedIn) return null;
  return <>{children}</>;
}
