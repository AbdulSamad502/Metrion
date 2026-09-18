"use client";

import { useSignIn } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthCard } from "@/components/ui/AuthCard";
import { Button } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { callClerk, errorText, isStaleResourceError } from "@/lib/clerkErrors";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** Password reset — auth.md I2/§6.4, delegated entirely to Clerk. Four steps: request a
 * code, verify it, THEN set a new password, then land in the app like any other sign-in.
 *
 * Verify and set-password are deliberately separate steps/requests, not one combined
 * form — that's not a UI preference, it's how Clerk's own API is documented to work:
 * `resetPasswordEmailCode.verifyCode()` is what moves `signIn.status` to
 * `needs_new_password`; only after that has actually happened does
 * `submitPassword()` make sense to call. Doing both in one submit handler worked
 * mechanically (the calls still happened in the right order) but showed both fields at
 * once, which is confusing and doesn't match the verified-then-act shape of the flow.
 *
 * See clerkErrors.ts for why every call goes through `callClerk()`/`errorText()`. */
export default function ForgotPasswordPage() {
  const { signIn, fetchStatus } = useSignIn();
  const router = useRouter();
  const [step, setStep] = useState<"request" | "code" | "newPassword">("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [staleResource, setStaleResource] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);

  const guard = useSubmitGuard();
  const submitting = fetchStatus === "fetching";

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const t = setTimeout(() => setResendCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendCooldown]);

  // Deliberately never reveals whether `email` has an account (enumeration protection,
  // auth.md security posture) — same UI on success or "no such account". Only a genuine
  // infrastructure failure (stale client, Clerk unreachable) breaks that pattern, and even
  // then only with a generic message, never one that hints at account existence.
  const requestCode = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      const { error } = await callClerk(() => signIn.create({ identifier: email }));
      if (!error) {
        await callClerk(() => signIn.resetPasswordEmailCode.sendCode());
      }
      setStep("code");
      setResendCooldown(30);
    });
  };

  const resendCode = () =>
    guard(async () => {
      if (resendCooldown > 0) return;
      await callClerk(() => signIn.resetPasswordEmailCode.sendCode());
      setResendCooldown(30);
    });

  const verifyCode = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      const { error } = await callClerk(() => signIn.resetPasswordEmailCode.verifyCode({ code }));
      if (error) {
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
        return;
      }
      setStep("newPassword");
    });
  };

  const submitNewPassword = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setGlobalError(null);
      const { error } = await callClerk(() => signIn.resetPasswordEmailCode.submitPassword({ password: newPassword }));
      if (error) {
        if (isStaleResourceError(error)) setStaleResource(true);
        else setGlobalError(errorText(error));
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
      }
    });
  };

  if (staleResource) {
    return (
      <AuthCard title="Let's try that again" subtitle="This reset link has expired">
        <p className="text-sm" style={{ color: "var(--text-4)" }}>
          Password reset codes only last a little while. Start over to get a fresh one.
        </p>
        <Button type="button" className="mt-4" onClick={() => window.location.reload()}>
          Start over
        </Button>
      </AuthCard>
    );
  }

  if (step === "code") {
    return (
      <AuthCard title="Check your email" subtitle={`If an account exists for ${email}, a code is on its way`}>
        <form onSubmit={verifyCode} className="flex flex-col gap-4">
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
            Verify code
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

  if (step === "newPassword") {
    return (
      <AuthCard title="Set a new password" subtitle="Code verified — choose a new password">
        <form onSubmit={submitNewPassword} className="flex flex-col gap-4">
          <FormField
            label="New password"
            type="password"
            required
            minLength={10}
            autoFocus
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          {globalError && (
            <p className="text-sm" style={{ color: "var(--negative)" }}>
              {globalError}
            </p>
          )}
          <Button type="submit" loading={submitting}>
            Reset password
          </Button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Forgot password?"
      subtitle="We'll email you a reset code"
      footer={
        <Link href="/sign-in" style={{ color: "var(--text-6)" }}>
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={requestCode} className="flex flex-col gap-4">
        <FormField
          label="Email address"
          type="email"
          required
          autoFocus
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {globalError && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            {globalError}
          </p>
        )}
        <Button type="submit" loading={submitting}>
          Send reset code
        </Button>
      </form>
    </AuthCard>
  );
}
