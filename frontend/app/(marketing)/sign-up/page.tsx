"use client";

import { useClerk, useSignUp } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { AuthCard } from "@/components/ui/AuthCard";
import { Button, GoogleIcon } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { callClerk, errorText, isIdentifierExistsError, isStaleResourceError, tryClerk } from "@/lib/clerkErrors";
import { estimatePasswordStrength } from "@/lib/passwordStrength";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** Custom sign-up — auth.md I2. Two steps: create (password or Google), then the
 * email verification code Clerk requires before the account is usable (I5).
 *
 * Every Clerk call goes through `callClerk()` and every resulting message through
 * `errorText()` — see clerkErrors.ts for why: reading the wrong `errors` object is a
 * stale-closure bug, and echoing Clerk's raw error text leaks developer-facing copy
 * ("We were unable to complete a GET request for this Client...") straight to a seller.
 * `globalError` is the ONLY place any error renders — no field also duplicates it inline,
 * which was the other bug (the same message rendering twice). */
export default function SignUpPage() {
  const { signUp, fetchStatus } = useSignUp();
  const clerk = useClerk();
  const router = useRouter();
  const [step, setStep] = useState<"form" | "verify">("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [accountExists, setAccountExists] = useState(false);
  const [staleResource, setStaleResource] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);

  const guard = useSubmitGuard();
  const submitting = fetchStatus === "fetching";
  const strength = useMemo(() => estimatePasswordStrength(password), [password]);

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const t = setTimeout(() => setResendCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendCooldown]);

  const finalizeAndGo = async () => {
    await signUp.finalize({
      navigate: ({ decorateUrl }) => {
        const url = decorateUrl("/onboarding");
        if (url.startsWith("http")) window.location.href = url;
        else router.push(url);
      },
    });
  };

  const continueWithGoogle = () =>
    guard(async () => {
      setGlobalError(null);
      const { error } = await tryClerk(() =>
        clerk.client.signUp.authenticateWithRedirect({
          // The stable, documented redirect API — see sign-in's identical comment.
          strategy: "oauth_google",
          redirectUrl: "/sso-callback",
          redirectUrlComplete: "/onboarding",
        }),
      );
      if (error) {
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
      }
    });

  const submitPassword = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      setAccountExists(false);
      const { error } = await callClerk(() => signUp.password({ emailAddress: email, password }));
      if (error) {
        if (isStaleResourceError(error)) {
          setStaleResource(true);
        } else if (isIdentifierExistsError(error)) {
          setAccountExists(true);
        } else {
          setGlobalError(errorText(error));
        }
        return;
      }
      if (signUp.status === "complete") {
        await finalizeAndGo();
        return;
      }
      if (signUp.unverifiedFields.includes("email_address")) {
        const { error: sendError } = await callClerk(() => signUp.verifications.sendEmailCode());
        if (sendError) {
          if (isStaleResourceError(sendError)) setStaleResource(true);
          else setGlobalError(errorText(sendError));
          return;
        }
        setStep("verify");
        setResendCooldown(30);
      }
    });
  };

  const resendCode = () =>
    guard(async () => {
      if (resendCooldown > 0) return;
      setGlobalError(null);
      const { error } = await callClerk(() => signUp.verifications.sendEmailCode());
      if (error) {
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
        return;
      }
      setResendCooldown(30);
    });

  const submitCode = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      const { error } = await callClerk(() => signUp.verifications.verifyEmailCode({ code }));
      if (error) {
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
        return;
      }
      if (signUp.status === "complete") await finalizeAndGo();
    });
  };

  if (staleResource) {
    return (
      <AuthCard title="Let's try that again" subtitle="This sign-up attempt has expired">
        <p className="text-sm" style={{ color: "var(--text-4)" }}>
          It looks like this page has been open for a while, or was started somewhere else.
          Refreshing will start a clean sign-up.
        </p>
        <Button type="button" className="mt-4" onClick={() => window.location.reload()}>
          Refresh and try again
        </Button>
      </AuthCard>
    );
  }

  if (step === "verify") {
    return (
      <AuthCard title="Check your email" subtitle={`We sent a code to ${email}`}>
        <form onSubmit={submitCode} className="flex flex-col gap-4">
          <FormField
            label="Verification code"
            type="text"
            inputMode="numeric"
            required
            autoFocus
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          {globalError && (
            <p className="text-sm" style={{ color: "var(--negative)" }}>
              {globalError}
            </p>
          )}
          <Button type="submit" loading={submitting}>
            Verify
          </Button>
          <button
            type="button"
            onClick={resendCode}
            disabled={resendCooldown > 0 || submitting}
            className="text-xs font-semibold disabled:opacity-50"
            style={{ color: "var(--text-6)" }}
          >
            {resendCooldown > 0 ? `Resend code (${resendCooldown}s)` : "Resend code"}
          </button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create your account"
      subtitle="Get started with Metrion"
      footer={
        <span style={{ color: "var(--text-6)" }}>
          Already have an account?{" "}
          <Link href="/sign-in" style={{ color: "var(--accent)", fontWeight: 700 }}>
            Sign in
          </Link>
        </span>
      }
    >
      <Button type="button" variant="secondary" onClick={continueWithGoogle} disabled={submitting}>
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
        <FormField
          label="Password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {password.length > 0 && (
          <div className="-mt-2 flex items-center gap-2" aria-live="polite">
            <div className="flex h-1 flex-1 gap-1">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-full flex-1 rounded-full transition-colors"
                  style={{
                    background:
                      i < strength.score
                        ? strength.score >= 3
                          ? "var(--accent)"
                          : "var(--warning)"
                        : "var(--border-subtle)",
                  }}
                />
              ))}
            </div>
            <span className="text-xs" style={{ color: "var(--text-7)" }}>
              {strength.label}
            </span>
          </div>
        )}
        <p className="-mt-2 text-xs" style={{ color: "var(--text-7)" }}>
          At least 10 characters — no special characters required. We check new passwords
          against known data breaches.
        </p>

        {accountExists && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            An account with this email already exists.{" "}
            <Link href="/sign-in" style={{ color: "var(--accent)", fontWeight: 700 }}>
              Sign in instead
            </Link>
          </p>
        )}

        {!accountExists && globalError && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            {globalError}
          </p>
        )}

        {/* Required by Clerk's bot sign-up protection (invisible unless a challenge is needed). */}
        <div id="clerk-captcha" />

        <Button type="submit" loading={submitting}>
          Create account
        </Button>
      </form>
    </AuthCard>
  );
}
