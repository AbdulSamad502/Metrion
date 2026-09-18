"use client";

import { useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { Button } from "@/components/ui/Button";
import { FormField } from "@/components/ui/FormField";
import { errorText } from "@/lib/clerkErrors";
import { estimatePasswordStrength } from "@/lib/passwordStrength";
import { useAppSession } from "@/lib/useAppSession";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** Account security settings. Exists specifically to close the auth.md gap: a user who
 * originally signed up with Google only has no password credential, and previously had
 * no way to add one — the password sign-in form could only ever reject them. This page
 * is that path, using Clerk's own supported mechanism (`user.updatePassword`) so it's the
 * SAME Clerk user, tenant and membership throughout — never a second account. */
export default function SettingsPage() {
  const { session, error, displayName, roleLabel, user } = useAppSession();

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--negative)" }}>
        {error}
      </div>
    );
  }

  if (!session || !user) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--text-5)" }}>
        Loading…
      </div>
    );
  }

  const googleAccount = user.externalAccounts.find((a) => a.provider === "google");

  return (
    <div className="flex" style={{ background: "var(--bg-base)" }}>
      <Sidebar userName={displayName} roleLabel={roleLabel} active="Settings" />
      <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar title="Settings" subtitle="Account and security" />
        <div className="flex-1 overflow-y-auto px-8 py-7">
          <div className="mx-auto flex max-w-xl flex-col gap-6">
            <SignInMethodsCard googleConnected={!!googleAccount} passwordEnabled={user.passwordEnabled} />
            <PasswordCard user={user} passwordEnabled={user.passwordEnabled} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-6"
      style={{ background: "var(--bg-card)", backdropFilter: "blur(34px) saturate(190%)", border: "1px solid var(--border-default)" }}
    >
      {children}
    </div>
  );
}

function SignInMethodsCard({ googleConnected, passwordEnabled }: { googleConnected: boolean; passwordEnabled: boolean }) {
  return (
    <Card>
      <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
        Sign-in methods
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        How you can sign in to Metrion.
      </div>
      <div className="mt-4 flex flex-col gap-2.5">
        <MethodRow label="Google" connected={googleConnected} />
        <MethodRow label="Email & password" connected={passwordEnabled} />
      </div>
    </Card>
  );
}

function MethodRow({ label, connected }: { label: string; connected: boolean }) {
  return (
    <div
      className="flex items-center justify-between rounded-lg px-3.5 py-2.5"
      style={{ background: "var(--bg-input)", border: "1px solid var(--border-subtle)" }}
    >
      <span className="text-sm" style={{ color: "var(--text-3)" }}>
        {label}
      </span>
      <span
        className="text-xs font-semibold"
        style={{ color: connected ? "var(--accent)" : "var(--text-7)" }}
      >
        {connected ? "Connected" : "Not set up"}
      </span>
    </div>
  );
}

type AppUser = NonNullable<ReturnType<typeof useAppSession>["user"]>;

function PasswordCard({ user, passwordEnabled }: { user: AppUser; passwordEnabled: boolean }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const strength = estimatePasswordStrength(newPassword);
  const guard = useSubmitGuard();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    return guard(async () => {
      setError(null);
      setSuccess(false);
      if (newPassword !== confirmPassword) {
        setError("Passwords don't match.");
        return;
      }
      setSubmitting(true);
      try {
        await user.updatePassword({
          newPassword,
          ...(passwordEnabled ? { currentPassword } : {}),
          // Any other signed-in device/session gets logged out on a password change — the
          // standard assumption is that a password change may be in response to a
          // compromise, so stale sessions shouldn't survive it.
          signOutOfOtherSessions: true,
        });
        await user.reload();
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setSuccess(true);
      } catch (e) {
        setError(errorText(e));
      } finally {
        setSubmitting(false);
      }
    });
  };

  return (
    <Card>
      <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
        {passwordEnabled ? "Change password" : "Add a password"}
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        {passwordEnabled
          ? "Update the password used for email sign-in."
          : "Your account currently only signs in with Google. Add a password so you can also sign in with your email address — this is the same account, same workspace, nothing changes but the options you have to get in."}
      </div>

      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        {passwordEnabled && (
          <FormField
            label="Current password"
            type="password"
            required
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        )}
        <FormField
          label={passwordEnabled ? "New password" : "Password"}
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        {newPassword.length > 0 && (
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
        <FormField
          label="Confirm password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />

        {error && (
          <p className="text-sm" style={{ color: "var(--negative)" }}>
            {error}
          </p>
        )}
        {success && (
          <p className="text-sm" style={{ color: "var(--accent)" }}>
            {passwordEnabled ? "Password updated." : "Password added — you can now sign in with either Google or email and password."}
          </p>
        )}

        <Button type="submit" loading={submitting}>
          {passwordEnabled ? "Update password" : "Add password"}
        </Button>
      </form>
    </Card>
  );
}
