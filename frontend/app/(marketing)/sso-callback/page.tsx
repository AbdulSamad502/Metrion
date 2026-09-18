import { AuthenticateWithRedirectCallback } from "@clerk/nextjs";

/** Lands here after Google redirects back to us. Clerk finishes the OAuth exchange and
 * then honors the NEXT_PUBLIC_CLERK_SIGN_IN/UP_FALLBACK_REDIRECT_URL env vars (/onboarding). */
export default function SSOCallbackPage() {
  return <AuthenticateWithRedirectCallback />;
}
