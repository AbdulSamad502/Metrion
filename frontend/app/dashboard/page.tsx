"use client";

import { PAGE_COPY } from "@/lib/navigation";
import Link from "next/link";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ProfitSnapshot } from "@/components/dashboard/ProfitSnapshot";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { Stat } from "@/components/ui/Stat";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { agentMeta, agentTier, TIER_LABEL, useAgentRoster } from "@/lib/agents";
import { useBusinessHealth } from "@/lib/useBusinessHealth";
import { useCiSummary } from "@/lib/useCiSummary";
import { useShell } from "@/lib/ShellContext";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

/** The post-auth landing screen. Reading order is the point:
 *   1. Business state   — what needs attention, with where each kind of item is handled
 *   2. Profit snapshot  — the latest SAVED CFO results as the backend presented them, with how current they are
 *   3. What matters now — the things that need a decision, each with its next step
 *      (beside it: opportunities and competitor-market counts)
 *   4. Agent activity   — who is working, and what they last did
 *
 * Every figure comes from a real response (`/ceo/state/health`, `/ci/summary`, the shared
 * notifications feed, `/ceo-hub/agents`). There is deliberately NO headline profit number: the backend has no
 * portfolio-level profit endpoint, and computing money in the browser breaks the project's hard
 * rule. Where data does not exist the page says so and points at the screen that produces it. */
export default function DashboardPage() {
  return (
    <DashboardShell {...PAGE_COPY["overview"]}>
      <Overview />
    </DashboardShell>
  );
}

function Overview() {
  const ci = useCiSummary();
  const { health, refresh, refreshing, checkedAt } = useBusinessHealth();
  return (
    <div className="mt-content mt-stack" style={{ gap: 24 }}>
      <BusinessState />
      <ProfitSnapshot health={health} onRefresh={refresh} refreshing={refreshing} checkedAt={checkedAt} />
      {/* Two balanced columns that each start at the top: attention + agent activity on the left, opportunities + market watch on the right.
          (Agent activity used to sit below the grid, so the shorter column left a tall empty gap above it.) */}
      <div className="grid grid-cols-1 items-start gap-x-8 gap-y-6 xl:grid-cols-12">
        <div className="flex flex-col gap-6 xl:col-span-7">
          <WhatMattersNow />
          <AgentActivity lastResearchAt={ci.summary?.lastResearchAt} />
        </div>
        <div className="flex flex-col gap-6 xl:col-span-5">
          <Opportunities />
          <MarketWatch ci={ci} />
        </div>
      </div>
    </div>
  );
}

/** One sentence on what needs attention, with where each kind of item is handled. How current the saved profit results are is said once, in the profit snapshot. */
function BusinessState() {
  const { displayName, notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const total = requests + alerts;
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  // A feed that failed is UNKNOWN, not empty: "nothing needs your attention" may only be said about what was actually checked.
  const failed = [n.alertsStatus === "error" ? "competitor alerts" : null, n.dataRequestsStatus === "error" ? "CFO data requests" : null].filter((x): x is string => x !== null);
  const parts = [
    requests > 0 ? { label: `${requests} data ${requests === 1 ? "request" : "requests"} from the CFO`, href: "/dashboard/cfo#anomalies" } : null,
    alerts > 0 ? { label: `${alerts} competitor ${alerts === 1 ? "alert" : "alerts"} in the last ${ALERT_WINDOW_DAYS} days`, href: "/dashboard/competitors" } : null,
  ].filter((x): x is { label: string; href: string } => x !== null);

  return (
    <section aria-labelledby="ov-state" className="mt-panel mt-panel--elevated mt-surface--hero flex flex-col gap-4 rounded-2xl p-5 sm:p-6" data-testid="business-state">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="mt-eyebrow">Welcome back, {displayName.split(" ")[0]}</div>
          <h2 id="ov-state" className="t-headline mt-2" style={{ color: "var(--text-1)" }}>
            {loading ? (
              <span className="mt-skeleton inline-block h-8 w-80 max-w-full align-middle" aria-label="Loading your summary" />
            ) : total === 0 && failed.length > 0 ? (
              "We could not check everything."
            ) : total === 0 ? (
              "Nothing needs your attention right now."
            ) : (
              `${total} ${total === 1 ? "thing needs" : "things need"} your attention.`
            )}
          </h2>
        </div>
      </div>
      {!loading && total === 0 && failed.length === 0 && (
        <p className="t-body m-0 max-w-[70ch]" style={{ color: "var(--text-4)" }}>
          {`No competitor alerts in the last ${ALERT_WINDOW_DAYS} days and no open data requests.`}
        </p>
      )}
      {!loading && failed.length > 0 && (
        <div className="flex flex-wrap items-center gap-3" data-testid="attention-unchecked">
          <p className="t-body m-0 max-w-[70ch]" style={{ color: "var(--text-4)" }}>
            {total === 0 ? "This is not an all-clear: " : "There may be more: "}
            {failed.join(" and ")} could not be loaded.
          </p>
          <button type="button" onClick={n.reload} className="mt-btn mt-focus min-h-[36px] rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Try again
          </button>
        </div>
      )}
      {!loading && parts.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="What needs attention">
          {parts.map((p) => (
            <li key={p.href}>
              <Link href={p.href} className="mt-chip mt-focus inline-flex min-h-[36px] items-center gap-1.5 rounded-full px-3.5 py-1.5 t-body-sm font-semibold" style={{ color: "var(--text-2)", border: "1px solid var(--warning-border)" }}>
                {p.label} <Icon name="arrow" size={12} strokeWidth={1.9} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Competitor-watch counts from `/ci/summary`. These are market signals, not profit, so they sit below the profit snapshot. */
function MarketWatch({ ci }: { ci: ReturnType<typeof useCiSummary> }) {
  const { summary } = ci;
  if (ci.forbidden) return null;
  return (
    <Section title="Market watch" panel={false}>
      {ci.error && (
        <div className="mb-3">
          <ErrorNotice message={summary ? `${ci.error} Showing the last counts that loaded.` : ci.error} onRetry={ci.reload} />
        </div>
      )}
      {ci.error && !summary ? null : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-5 [&>*:nth-child(odd)]:pl-0" data-testid="market-watch">
          <Stat
            label="Competitors tracked"
            href="/dashboard/competitors"
            loading={!summary}
            value={summary ? String(summary.trackedCompetitors) : null}
            hint={
              summary && summary.trackedCompetitors === 0
                ? "Add your first competitor"
                : summary?.lastResearchAt
                  ? `Last research ${new Date(summary.lastResearchAt).toLocaleDateString()}`
                  : "No research run yet"
            }
          />
          <Stat label="Price changes · 7 days" href="/dashboard/competitors" loading={!summary} value={summary ? String(summary.recentPriceEvents7d) : null} />
          <Stat
            label="Need manual entry"
            href="/dashboard/competitors"
            loading={!summary}
            value={summary ? String(summary.pendingManualEntry) : null}
            tone={summary && summary.pendingManualEntry > 0 ? "warning" : "default"}
            hint={summary && summary.pendingManualEntry > 0 ? "Evidence could not be read" : undefined}
          />
          <Stat
            label="Stale competitors"
            href="/dashboard/competitors"
            loading={!summary}
            value={summary ? String(summary.staleCompetitors) : null}
            tone={summary && summary.staleCompetitors > 0 ? "warning" : "default"}
            hint="No research in over 7 days"
          />
        </div>
      )}
    </Section>
  );
}

function WhatMattersNow() {
  const { notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest);
  // Threshold-breaching alerts first: those are the ones the engine itself flagged as alert-worthy.
  const alerts = [...n.alerts].sort((a, b) => Number(b.thresholdBreached) - Number(a.thresholdBreached));
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const failed = [n.alertsError, n.dataRequestsError].filter((e): e is string => Boolean(e));
  const rows = requests.length + alerts.length;

  return (
    <Section
      title="What matters now"
      panel={false}
      action={
        rows > 0 ? (
          <Link href="/dashboard/notifications" className="mt-focus inline-flex min-h-9 items-center sm:min-h-6 gap-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
            See all <Icon name="arrow" size={12} strokeWidth={1.9} />
          </Link>
        ) : undefined
      }
    >
      {loading ? (
        <LoadingState lines={4} label="Loading what needs attention" />
      ) : (
        <div className="flex flex-col gap-3">
          {failed.map((f, i) => (
            <ErrorNotice key={i} message={f} onRetry={n.reload} />
          ))}
          {rows === 0 ? (
            failed.length === 0 ? (
              <EmptyState
                compact
                icon="check"
                title="You're clear"
                description="When a competitor changes price or the CFO needs an input from you, it appears here with the next step."
              />
            ) : null /* a failed feed already said so above: no "all clear", and no empty box either */
          ) : (
            <ul className="mt-panel m-0 flex list-none flex-col px-3 py-1">
              {requests.slice(0, 4).map((r) => (
                <li key={r.id} className="mt-stripe mt-stripe--warning pl-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <Link href="/dashboard/cfo#anomalies" className="mt-row mt-focus flex items-center gap-4 rounded-lg px-1 py-3.5">
                    <StatusBadge tone="warning" dot>
                      CFO needs input
                    </StatusBadge>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
                        {r.requestedField}
                      </span>
                      {r.reason && (
                        <span className="block truncate t-body-sm" style={{ color: "var(--text-5)" }}>
                          {r.reason}
                        </span>
                      )}
                    </span>
                    <span className="flex flex-shrink-0 items-center gap-1 t-body-sm font-semibold" style={{ color: "var(--text-4)" }}>
                      Provide <Icon name="arrow" size={12} />
                    </span>
                  </Link>
                </li>
              ))}
              {alerts.slice(0, 5).map((a) => (
                <li key={a.priceEventId} className={`mt-stripe pl-2 ${a.thresholdBreached ? "mt-stripe--negative" : "mt-stripe--neutral"}`} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <Link href="/dashboard/competitors" className="mt-row mt-focus flex items-center gap-4 rounded-lg px-1 py-3.5">
                    <StatusBadge tone={a.thresholdBreached ? "negative" : "info"} dot>
                      {a.thresholdBreached ? "Alert-worthy" : "Competitor"}
                    </StatusBadge>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
                        {a.competitorLabel}
                      </span>
                      <span className="block truncate t-body-sm" style={{ color: "var(--text-5)" }}>
                        {a.message}
                      </span>
                    </span>
                    <span className="flex flex-shrink-0 items-center gap-1 t-body-sm font-semibold" style={{ color: "var(--text-4)" }}>
                      Review <Icon name="arrow" size={12} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Section>
  );
}

function Opportunities() {
  return (
    <Section title="Opportunities" panel={false}>
      <p className="t-body leading-relaxed" style={{ color: "var(--text-4)" }}>
        Product Intelligence finds product opportunities and supplier leads from public web signals. Research starts in the CEO Hub; Products keeps
        your saved reports. Opportunities are not summarised here.
      </p>
      <Link
        href="/dashboard/pi"
        className="mt-focus mt-3 inline-flex min-h-9 items-center sm:min-h-6 gap-1.5 t-body font-bold"
        style={{ color: "var(--text-3)" }}
      >
        Read saved research <Icon name="arrow" size={12} strokeWidth={1.9} />
      </Link>
    </Section>
  );
}

function AgentActivity({ lastResearchAt }: { lastResearchAt: string | null | undefined }) {
  const { agents, error, reload } = useAgentRoster();
  return (
    <Section
      title="Agent activity"
      panel={false}
      action={
        <Link href="/dashboard/ceo-hub" className="mt-focus inline-flex min-h-9 items-center sm:min-h-6 gap-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
          Open CEO Hub <Icon name="arrow" size={12} strokeWidth={1.9} />
        </Link>
      }
    >
      {error ? (
        <ErrorNotice message={error} onRetry={reload} />
      ) : !agents ? (
        <LoadingState lines={4} label="Loading agents" />
      ) : (
        <div className="mt-table-wrap">
          <table className="mt-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Availability</th>
                <th>Last activity</th>
                <th className="relative"><span className="sr-only">Open agent workspace</span></th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => {
                const meta = agentMeta(a.id);
                const tier = agentTier(a);
                // Only CI records activity today (its last research run); the rest say so.
                const last =
                  a.id === "CI"
                    ? lastResearchAt === undefined
                      ? "…"
                      : lastResearchAt
                        ? new Date(lastResearchAt).toLocaleString()
                        : "No research run yet"
                    : tier === "unavailable"
                      ? "—"
                      : "Not recorded";
                return (
                  <tr key={a.id}>
                    <td>
                      <span className="flex items-center gap-2.5">
                        <span style={{ color: tier === "connected" ? "var(--text-2)" : "var(--text-5)" }}>
                          <Icon name={meta.icon} size={16} />
                        </span>
                        {a.name}
                      </span>
                    </td>
                    <td>
                      <StatusBadge tone={tier === "connected" ? "accent" : "neutral"} dot>
                        {TIER_LABEL[tier]}
                      </StatusBadge>
                    </td>
                    <td style={{ color: "var(--text-4)" }}>{last}</td>
                    <td className="text-right">
                      {meta.href && (
                        <Link href={meta.href} aria-label={`Open ${a.name}`} className="mt-focus inline-flex min-h-6 min-w-6 items-center t-body-sm font-bold" style={{ color: "var(--text-3)" }}>
                          Open
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
