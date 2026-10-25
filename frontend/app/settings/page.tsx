"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { useAuth, useUser } from "@clerk/nextjs";
import { useEffect, useState, useSyncExternalStore } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ErrorBanner, LoadingLines, Pill } from "@/components/overview/parts";
import { FormField } from "@/components/ui/FormField";
import "@/components/overview/overview.css";
import "./settings.css";
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

  if (!isLoaded || !user) return <div className="ov"><LoadingLines label="Loading your account…" /></div>;

  const googleAccount = user.externalAccounts.find((a) => a.provider === "google");

  return (
    <div className="ov mt-content">
      <Tabs tabs={[...SETTINGS_TABS]} active={tab} onChange={setTab} label="Settings sections" idPrefix="settings" />
      <TabPanel id="account" active={tab} idPrefix="settings">
        <div className="set-stack">
          <div className="set-cols">
            <div className="ov-col"><PasswordCard user={user} passwordEnabled={user.passwordEnabled} /></div>
            <div className="ov-col">
              <AppearanceCard />
              {DEMO_AVAILABLE && <SampleDataCard />}
            </div>
          </div>
          <SignInMethodsCard googleConnected={!!googleAccount} passwordEnabled={user.passwordEnabled} />
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
      <Head title="Workspace" hint="You and your business." />
      <div>
        <button type="button" onClick={() => setEditing(true)} className="ov-btn ov-btn--brand min-h-10">
          Business details
        </button>
      </div>
      {editing && <BusinessDetailsDialog onClose={() => setEditing(false)} onSaved={() => toast.success("Business details saved.")} />}
      <dl className="set-list">
        {rows.map(([k, v]) => (
          <div key={k} className="set-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
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
      <Head
        title="Competitor digest"
        badge={<Pill tone="warn">Delivery not live yet</Pill>}
        hint="Your choice is saved. Digests aren’t sent yet."
      />
      <div>
        {forbidden ? (
          <p className="ov-body">
            Your role has no access to Competitor Intelligence.
          </p>
        ) : loadError ? (
          <ErrorBanner message={loadError} onRetry={() => void load()} />
        ) : !sub ? (
          <LoadingLines label="Loading your preference…" />
        ) : (
          <>
            <div role="group" aria-label="Digest frequency" aria-busy={saving} className="set-chips">
              {FREQUENCIES.map((f) => {
                const selected = sub.frequency === f.value;
                return (
                  <button
                    key={f.value}
                    type="button"
                    aria-pressed={selected}
                    disabled={saving}
                    onClick={() => void save(f.value)}
                    className="ci-pick mt-focus min-h-[40px]"
                    style={saving ? { opacity: 0.6 } : undefined}
                  >
                    {f.label}
                  </button>
                );
              })}
            </div>
            <div className="ov-meta" style={{ marginTop: 16 }} aria-live="polite">
              {saving ? (
                "Saving…"
              ) : saveError ? (
                <span role="alert" style={{ color: "var(--ov-bad)" }}>{saveError}</span>
              ) : saved ? (
                "Saved."
              ) : sub.isDefault ? (
                "Workspace default. You haven’t chosen yet."
              ) : null}
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return <section className="ov-card ov-rise">{children}</section>;
}

/** A card's heading and its one plain sentence. */
function Head({ title, hint, badge }: { title: string; hint?: React.ReactNode; badge?: React.ReactNode }) {
  return (
    <div>
      <div className="ov-card-head">
        <h2 className="ov-title">{title}</h2>
        {badge}
      </div>
      {hint && <p className="ov-meta" style={{ marginTop: 4 }}>{hint}</p>}
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
      <Head title="Appearance" hint="Saved on this device." />
      <div className="set-chips" role="group" aria-label="Theme">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            aria-pressed={theme === o.value}
            onClick={() => setTheme(o.value)}
            className="ci-pick mt-focus min-h-[40px]"
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
      <Head
        title="Sample data"
        badge={<Pill tone="warn">Preview only</Pill>}
        hint="Made-up figures to preview pages. Nothing is saved."
      />
      <div>
        <button
          type="button"
          aria-pressed={on}
          onClick={() => setDemo(!on)}
          className={`ov-btn min-h-10${on ? " ov-btn--brand" : ""}`}
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
      <Head title="Sign-in methods" hint="How you can sign in to Metrion." />
      <div className="set-list">
        <MethodRow label="Google" connected={googleConnected} />
        <MethodRow label="Email & password" connected={passwordEnabled} />
      </div>
    </Card>
  );
}

function MethodRow({ label, connected }: { label: string; connected: boolean }) {
  return (
    <div className="set-row">
      <span>{label}</span>
      {connected ? <Pill tone="good" icon="check">Connected</Pill> : <Pill>Not set up</Pill>}
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
      <Head
        title={passwordEnabled ? "Change password" : "Add a password"}
        hint={passwordEnabled
          ? "For email sign-in."
          : "You sign in with Google. Add a password to also use your email. Same account."}
      />

      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {passwordEnabled && (
          <FormField
            soft
            label="Current password"
            type="password"
            required
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        )}
        <FormField
          soft
          label={passwordEnabled ? "New password" : "Password"}
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        {newPassword.length > 0 && (
          <div className="set-strength" aria-live="polite">
            <div>
              {[0, 1, 2, 3].map((i) => (
                <i key={i} className={i < strength.score ? (strength.score >= 3 ? "on" : "warn") : ""} />
              ))}
            </div>
            <span className="ov-meta" style={{ color: "var(--text-6)" }}>
              {strength.label}
            </span>
          </div>
        )}
        <FormField
          soft
          label="Confirm password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />

        {error && (
          <p role="alert" className="ov-body" style={{ color: "var(--ov-bad)" }}>
            {error}
          </p>
        )}
        {success && (
          <p role="status" className="ov-body" style={{ color: "var(--ov-good)" }}>
            {passwordEnabled ? "Password updated." : "Password added — you can now sign in with either Google or email and password."}
          </p>
        )}

        <button type="submit" disabled={submitting} className="ov-btn ov-btn--brand min-h-10" style={{ width: "fit-content" }}>
          {submitting ? "Please wait…" : passwordEnabled ? "Update password" : "Add password"}
        </button>
      </form>
    </Card>
  );
}
