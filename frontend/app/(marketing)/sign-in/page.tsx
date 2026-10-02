"use client";

import { useClerk, useSignIn } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard } from "@/components/ui/AuthCard";
import { Button, GoogleIcon } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { callClerk, errorText, isSessionExistsError, isStaleResourceError, isWrongStrategyError, tryClerk } from "@/lib/clerkErrors";
import { useRedirectIfSignedIn } from "@/lib/useRedirectIfSignedIn";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** Custom sign-in — auth.md I2 (Google + email/password), built against Clerk's
 * useSignIn() hook rather than the prebuilt <SignIn/> so it matches
 * docs/design/frontend-design pixel-for-pixel.
 *
 * See clerkErrors.ts for why every call is wrapped in `callClerk()` and every message
 * goes through `errorText()` rather than Clerk's raw text, and why `globalError` is the
 * only place any error is ever rendered (no duplicate inline field message). */
export default function SignInPage() {
  useRedirectIfSignedIn();
  const { signIn, fetchStatus } = useSignIn();
  const clerk = useClerk();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [wrongStrategy, setWrongStrategy] = useState(false);
  const [staleResource, setStaleResource] = useState(false);
  const [googleRedirecting, setGoogleRedirecting] = useState(false);

  const guard = useSubmitGuard();
  const submitting = fetchStatus === "fetching";

  const continueWithGoogle = () =>
    guard(async () => {
      setGlobalError(null);
      // The stable, documented redirect API (unlike the newer sso() facade, whose
      // redirect params are still ambiguous/incomplete upstream) — see the doc comment
      // on AuthenticateWithRedirectParams: redirectUrl is the callback route that mounts
      // <AuthenticateWithRedirectCallback/>, redirectUrlComplete is where we land after.
      setGoogleRedirecting(true);
      const start = () =>
        tryClerk(() =>
          clerk.client.signIn.authenticateWithRedirect({
            strategy: "oauth_google",
            redirectUrl: "/sso-callback",
            redirectUrlComplete: "/onboarding",
          }),
        );
      let { error } = await start();
      if (error && isSessionExistsError(error)) {
        // A leftover session in this browser blocks a new sign-in. Clear it and retry in
        // the same click, so it's still one click for the seller.
        await tryClerk(() => clerk.signOut());
        ({ error } = await start());
      }
      // On success the browser is already navigating to Google — keep the loading state.
      if (error) {
        setGoogleRedirecting(false);
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
      }
    });

  const submitPassword = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      setWrongStrategy(false);
      const { error } = await callClerk(() => signIn.password({ identifier: email, password }));
      if (error) {
        if (isSessionExistsError(error)) {
          // Leftover session in this browser blocks a new sign-in: clear it and reload clean.
          await clerk.signOut({ redirectUrl: "/sign-in" });
        } else if (isStaleResourceError(error)) {
          setStaleResource(true);
        } else if (isWrongStrategyError(error)) {
          setWrongStrategy(true);
        } else {
          setGlobalError(errorText(error));
        }
        return;
      }
      if (signIn.status === "complete") {
        await signIn.finalize({
          navigate: ({ decorateUrl }) => {
            const url = decorateUrl("/onboarding");
            if (url.startsWith("http")) window.location.href = url;
            else router.push(url);
          },
        });
      } else {
        setGlobalError("Additional verification is required for this account.");
      }
    });
  };

  if (staleResource) {
    return (
      <AuthCard title="Let's try that again" subtitle="This page has expired">
        <p className="text-sm" style={{ color: "var(--text-4)" }}>
          It looks like this page has been open for a while, or was started somewhere else.
          Refreshing will start clean.
        </p>
        <Button type="button" className="mt-4" onClick={() => window.location.reload()}>
          Refresh and try again
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Welcome back"
      subtitle="Sign in to continue to Metrion"
      footer={
        <span style={{ color: "var(--text-6)" }}>
          Don&apos;t have an account?{" "}
          <Link href="/sign-up" style={{ color: "var(--accent)", fontWeight: 700 }}>
            Sign up
          </Link>
        </span>
      }
    >
      <Button
        type="button"
        variant="secondary"
        onClick={continueWithGoogle}
        disabled={submitting}
        loading={googleRedirecting}
        loadingText="Redirecting to Google…"
      >
        <GoogleIcon />
        Continue with Google
      </Button>

      <div className="my-5 flex items-center gap-3">
        <div className="h-px flex-1" style={{ background: "var(--border-subtle)" }} />
        <span className="text-xs" style={{ color: "var(--text-7)" }}>
          or
        </span>
        <div className="h-px flex-1" style={{ background: "var(--border-subtle)" }} />
      </div>

      <form onSubmit={submitPassword} className="flex flex-col gap-4">
        <FormField
          label="Email address"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="flex flex-col gap-1.5">
          <FormField
            label="Password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Link
            href="/forgot-password"
            className="self-end text-xs font-semibold"
            style={{ color: "var(--text-6)" }}
          >
            Forgot password?
          </Link>
        </div>

        {wrongStrategy && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            An account already exists for this email, signed in with Google — it doesn&apos;t have a
            password yet. Use &quot;Continue with Google&quot; above, then add a password from{" "}
            <strong>Settings → Security</strong> so you can use either from then on.
          </p>
        )}

        {!wrongStrategy && globalError && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            {globalError}
          </p>
        )}

        <Button type="submit" loading={submitting}>
          Sign in
        </Button>
      </form>
    </AuthCard>
  );
}
