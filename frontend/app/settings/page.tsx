"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { useEffect, useState, useSyncExternalStore } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { Button } from "@/components/ui/Button";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { FormField } from "@/components/ui/FormField";
import { LoadingState } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { ApiError, apiFetch, type DigestSubscription } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { BusinessDetailsDialog } from "@/components/profile/BusinessDetailsDialog";
import { errorText } from "@/lib/clerkErrors";
import { estimatePasswordStrength } from "@/lib/passwordStrength";
import { useToast } from "@/components/ui/Toast";
import { getServerTheme, getTheme, setTheme, subscribeTheme, type Theme } from "@/lib/theme";
import { useShell } from "@/lib/ShellContext";
import { useHashTab } from "@/lib/useHashTab";
import { useSubmitGuard } from "@/lib/useSubmitGuard";
import { DEMO_AVAILABLE, setDemo, useDemo } from "@/lib/demo/mode";

const SETTINGS_TABS = [
  { id: "account", label: "Account & security" },
  { id: "business", label: "Business" },
  { id: "notifications", label: "Competitor digest" },
] as const;

/** Settings. "Account & security" exists specifically to close the auth.md gap: a user who
 * originally signed up with Google only has no password credential, and previously had no way to
 * add one — that tab is that path, using Clerk's own supported mechanism (`user.updatePassword`)
 * so it's the SAME Clerk user, tenant and membership throughout — never a second account.
 * "Business" shows the workspace and opens the mandatory Business details form (business-profile.md), and
 * "Competitor digest" (hash `#notifications`, kept so old links work) edits the one preference the backend really stores (the CI digest
 * subscription). Marketplace and WhatsApp settings are intentionally absent: no backend exists. */
export default function SettingsPage() {
  return (
    <DashboardShell {...PAGE_COPY["settings"]}>
      <SettingsWorkspace />
    </DashboardShell>
  );
}

function SettingsWorkspace() {
  const { user, isLoaded } = useUser();
  const [tab, setTab] = useHashTab(SETTINGS_TABS.map((t) => t.id), "account");

  if (!isLoaded || !user) return <LoadingState label="Loading your account…" />;

  const googleAccount = user.externalAccounts.find((a) => a.provider === "google");

  return (
    <div className="mt-content flex max-w-3xl flex-col gap-6">
      <Tabs tabs={[...SETTINGS_TABS]} active={tab} onChange={setTab} label="Settings sections" idPrefix="settings" />
      <TabPanel id="account" active={tab} idPrefix="settings">
        <div className="flex flex-col gap-6">
          <AppearanceCard />
          {DEMO_AVAILABLE && <SampleDataCard />}
          <SignInMethodsCard googleConnected={!!googleAccount} passwordEnabled={user.passwordEnabled} />
          <PasswordCard user={user} passwordEnabled={user.passwordEnabled} />
        </div>
      </TabPanel>
      <TabPanel id="business" active={tab} idPrefix="settings">
        <BusinessCard email={user.primaryEmailAddress?.emailAddress ?? null} />
      </TabPanel>
      <TabPanel id="notifications" active={tab} idPrefix="settings">
        <DigestPreferenceCard />
      </TabPanel>
    </div>
  );
}

function BusinessCard({ email }: { email: string | null }) {
  const { session, displayName, roleLabel } = useShell();
  const [editing, setEditing] = useState(false);
  const toast = useToast();
  const rows: [string, string][] = [
    ["Name", displayName],
    ["Email", email ?? "Not available"],
    ["Email verified", session.emailVerified ? "Yes" : "No"],
    ["Role in this workspace", roleLabel],
    ["Membership", session.membershipStatus ? session.membershipStatus.toLowerCase() : "Not available"],
  ];
  return (
    <Card>
      <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
        Workspace
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        How Metrion knows you, and the details of your business that its assistants use to tailor their advice.
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="mt-btn mt-focus min-h-[44px] rounded-xl px-4 py-2 text-sm font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          Business details
        </button>
      </div>
      {editing && <BusinessDetailsDialog onClose={() => setEditing(false)} onSaved={() => toast.success("Business details saved.")} />}
      <dl className="mt-4 flex flex-col gap-2.5">
        {rows.map(([k, v]) => (
          <div
            key={k}
            className="flex items-center justify-between gap-4 rounded-lg px-3.5 py-2.5"
            style={{ background: "var(--bg-input)", border: "1px solid var(--border-subtle)" }}
          >
            <dt className="text-sm" style={{ color: "var(--text-5)" }}>
              {k}
            </dt>
            <dd className="truncate text-sm font-semibold" style={{ color: "var(--text-2)" }}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

const FREQUENCIES: { value: DigestSubscription["frequency"]; label: string }[] = [
  { value: "NONE", label: "Off" },
  { value: "DAILY", label: "Daily" },
  { value: "WEEKLY", label: "Weekly" },
];

function DigestPreferenceCard() {
  const { getToken } = useAuth();
  const [sub, setSub] = useState<DigestSubscription | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    setLoadError(null);
    try {
      setSub(await apiFetch<DigestSubscription>("/api/v1/ci/digest/subscription", await getToken()));
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setForbidden(true);
      else setLoadError(friendlyApiError(e, "Could not reach the backend"));
    }
  };

  useEffect(() => {
    (async () => {
      await load();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (frequency: DigestSubscription["frequency"]) => {
    if (!sub) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      await apiFetch("/api/v1/ci/digest/subscription", await getToken(), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frequency, channel: sub.channel, enabled: frequency !== "NONE" }),
      });
      setSub({ ...sub, frequency, enabled: frequency !== "NONE", isDefault: false });
      setSaved(true);
    } catch (e) {
      setSaveError(friendlyApiError(e, "Could not save your preference"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
          Competitor digest
        </div>
        <StatusBadge tone="warning">Delivery not live yet</StatusBadge>
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        Your preferred digest frequency is stored, but Metrion does not send digests yet — the digest preview lives in
        Competitors. Email and WhatsApp delivery are not available.
      </div>
      <div className="mt-4">
        {forbidden ? (
          <div className="text-sm" style={{ color: "var(--text-5)" }}>
            Your role does not have access to Competitor Intelligence, so there is no digest to configure.
          </div>
        ) : loadError ? (
          <ErrorNotice message={loadError} onRetry={() => void load()} />
        ) : !sub ? (
          <LoadingState label="Loading your preference…" />
        ) : (
          <>
            <div role="group" aria-label="Digest frequency" aria-busy={saving} className="flex flex-wrap gap-2">
              {FREQUENCIES.map((f) => {
                const selected = sub.frequency === f.value;
                return (
                  <button
                    key={f.value}
                    type="button"
                    aria-pressed={selected}
                    disabled={saving}
                    onClick={() => void save(f.value)}
                    className="mt-chip mt-focus min-h-[40px] rounded-xl px-4 py-2 t-body-sm font-semibold disabled:opacity-60"
                    style={{
                      color: selected ? "var(--accent)" : "var(--text-4)",
                      background: selected ? "var(--accent-fill-default)" : "transparent",
                      border: `1px solid ${selected ? "var(--accent-border-default)" : "var(--border-default)"}`,
                    }}
                  >
                    {f.label}
                  </button>
                );
              })}
            </div>
            <div className="mt-3 text-xs" style={{ color: "var(--text-6)" }} aria-live="polite">
              {saving ? (
                "Saving…"
              ) : saveError ? (
                <span role="alert" style={{ color: "var(--negative)" }}>{saveError}</span>
              ) : saved ? (
                "Saved."
              ) : sub.isDefault ? (
                "Showing the workspace default — you have not chosen a preference yet."
              ) : null}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-panel" style={{ padding: "22px 24px" }}>
      {children}
    </div>
  );
}

/** Dark is the default look; light is opt-in. The choice is kept in this browser only, and the CEO Hub always stays dark. */
function AppearanceCard() {
  const theme = useSyncExternalStore(subscribeTheme, getTheme, getServerTheme);
  const options: { value: Theme; label: string }[] = [
    { value: "dark", label: "Dark" },
    { value: "light", label: "Light" },
  ];
  return (
    <Card>
      <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
        Appearance
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        Saved on this device. The CEO Hub stays dark.
      </div>
      <div className="mt-4 flex gap-2" role="group" aria-label="Theme">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={theme === o.value}
            onClick={() => setTheme(o.value)}
            className="mt-btn mt-focus min-h-[40px] rounded-xl px-4 text-sm font-bold"
            style={
              theme === o.value
                ? { background: "var(--accent)", color: "var(--accent-on-fill)" }
                : { border: "1px solid var(--border-hover)", color: "var(--text-3)" }
            }
          >
            {o.label}
          </button>
        ))}
      </div>
    </Card>
  );
}

/** Preview only (`NEXT_PUBLIC_ENABLE_DEMO_DATA=1`): fills the dashboards with hand-written sample responses so every page can be seen filled in. Sample figures are
 * fictional, nothing is saved, the CEO Hub never shows them, and a "Sample data" label stays on screen while it is on. */
function SampleDataCard() {
  const on = useDemo();
  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <div className="text-base font-bold" style={{ color: "var(--text-2)" }}>
          Sample data
        </div>
        <StatusBadge tone="warning">Preview only</StatusBadge>
      </div>
      <div className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
        Fill the dashboards with made-up sample figures to see how they look once a seller has uploaded reports. They are not your numbers, nothing is saved, and the CEO Hub does not use them.
      </div>
      <div className="mt-4">
        <button
          type="button"
          aria-pressed={on}
          onClick={() => setDemo(!on)}
          className="mt-btn mt-focus min-h-[40px] rounded-xl px-4 text-sm font-bold"
          style={on ? { background: "var(--accent)", color: "var(--accent-on-fill)" } : { border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
        >
          {on ? "Sample data is on — turn off" : "Fill with sample data"}
        </button>
      </div>
    </Card>
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
        style={{ color: connected ? "var(--accent)" : "var(--text-5)" }}
      >
        {connected ? "Connected" : "Not set up"}
      </span>
    </div>
  );
}

type AppUser = NonNullable<ReturnType<typeof useUser>["user"]>;

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
            <span className="text-xs" style={{ color: "var(--text-6)" }}>
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
          <p role="alert" className="text-sm" style={{ color: "var(--negative)" }}>
            {error}
          </p>
        )}
        {success && (
          <p role="status" className="text-sm" style={{ color: "var(--accent)" }}>
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
