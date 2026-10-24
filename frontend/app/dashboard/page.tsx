"use client";

import { PAGE_COPY } from "@/lib/navigation";
import Link from "next/link";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { HeaderContext } from "@/components/dashboard/HeaderContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { Stat } from "@/components/ui/Stat";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { HealthStrip } from "@/components/ceo/hub/HealthStrip";
import { agentMeta, agentTier, TIER_LABEL, useAgentRoster } from "@/lib/agents";
import { daysSince, latestAsOf, STALE_AFTER_DAYS, useBusinessHealth } from "@/lib/useBusinessHealth";
import type { HealthState } from "@/lib/useCeoHub";
import { useCiSummary } from "@/lib/useCiSummary";
import { useShell } from "@/lib/ShellContext";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

/** The post-auth landing screen. Reading order is the point:
 *   1. Business state   — what needs attention, plus how fresh the saved results are
 *   2. Profit snapshot  — the latest SAVED CFO results as the backend presented them
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
    <DashboardShell
      {...PAGE_COPY["overview"]}
      context={<HeaderContext kind="both" />}
    >
      <Overview />
    </DashboardShell>
  );
}

function Overview() {
  const ci = useCiSummary();
  const { health, refresh, refreshing } = useBusinessHealth();
  return (
    <div className="mt-content mt-stack" style={{ gap: 24 }}>
      <BusinessState health={health} />
      <ProfitSnapshot health={health} onRefresh={refresh} refreshing={refreshing} />
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

/** One sentence on what needs attention, then a freshness line saying which saved results the page is built on. */
function BusinessState({ health }: { health: HealthState }) {
  const { displayName, notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const total = requests + alerts;
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  // A feed that failed is UNKNOWN, not empty: "nothing needs your attention" may only be said about what was actually checked.
  const failed = [n.alertsStatus === "error" ? "competitor alerts" : null, n.dataRequestsStatus === "error" ? "CFO data requests" : null].filter((x): x is string => x !== null);
  const asOf = latestAsOf(health.entries);

  const age = daysSince(asOf);
  const stale = age !== null && age > STALE_AFTER_DAYS;
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
        <div className="flex flex-col items-start gap-1 sm:items-end" data-testid="data-freshness-badge">
          {health.status === "loading" && health.entries.length === 0 ? (
            <StatusBadge tone="neutral">Checking saved results…</StatusBadge>
          ) : health.status === "error" && health.entries.length === 0 ? (
            <StatusBadge tone="negative">Saved results unavailable</StatusBadge>
          ) : asOf ? (
            <StatusBadge tone={stale ? "warning" : "accent"} dot>{stale ? "Saved results are stale" : "Saved results are current"}</StatusBadge>
          ) : (
            <StatusBadge tone="neutral">No saved profit results yet</StatusBadge>
          )}
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
      <p className="t-meta m-0" style={{ color: "var(--text-5)" }} data-testid="data-freshness">
        {health.status === "loading" && health.entries.length === 0
          ? "Checking your saved results…"
          : health.status === "error" && health.entries.length === 0
            ? "Your saved results could not be loaded, so this page cannot say whether any exist. Try again in a moment."
          : asOf
            ? `Profit results shown are the latest saved ones, as of ${asOf.slice(0, 10)}${age !== null ? ` (${age === 0 ? "today" : age === 1 ? "1 day ago" : `${age} days ago`})` : ""}.${stale ? " They may not reflect recent orders; upload newer reports in Profit & Finance to refresh them." : ""}`
            : "No saved profit results yet. Upload a settlement or order report in Profit & Finance to compute them."}
      </p>
    </section>
  );
}

/** Competitor-watch counts from `/ci/summary`. These are market signals, not profit, so they sit below the profit snapshot. */
function MarketWatch({ ci }: { ci: ReturnType<typeof useCiSummary> }) {
  const { summary } = ci;
  if (ci.forbidden) return null;
  return (
    <Section title="Market watch" panel={false}>
      {ci.error ? (
        <ErrorNotice message={ci.error} />
      ) : (
        <div className="grid grid-cols-2 gap-x-4 gap-y-5" data-testid="market-watch">
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

/** The profit snapshot: the latest SAVED CFO results, shown exactly as the backend presented them (each with its period, as-of date and
 * provenance). It is not a portfolio headline: the backend has no portfolio-level revenue/profit/margin endpoint yet (tracked in
 * docs/design/ui-ux-phase1-audit.md §7), so nothing is summed or trended here. A missing result says so. */
function ProfitSnapshot({ health, onRefresh, refreshing }: { health: HealthState; onRefresh: () => void; refreshing: boolean }) {
  return (
    <Section
      title="Profit snapshot"
      panel={false}
      action={
        <Link href="/dashboard/cfo#profitability" className="mt-focus inline-flex min-h-9 items-center sm:min-h-6 gap-1 t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
          Open Profit &amp; Finance <Icon name="arrow" size={12} strokeWidth={1.9} />
        </Link>
      }
    >
      <HealthStrip health={health} onRefresh={onRefresh} refreshing={refreshing} />
      <p className="t-meta mt-3 max-w-[70ch]" style={{ color: "var(--text-6)" }}>
        Each result is one saved calculation with its own period and source. A single combined profit trend is not available yet.
      </p>
      <div className="mt-3 flex flex-wrap gap-2.5">
        <Link
          href="/dashboard/cfo#import"
          className="mt-btn mt-focus inline-flex items-center rounded-lg px-3.5 py-2 t-body font-semibold"
          style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}
        >
          Upload reports
        </Link>
        <Link
          href="/dashboard/ceo-hub"
          className="mt-btn mt-focus inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 t-body font-semibold"
          style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}
        >
          Ask where profit is leaking <Icon name="arrow" size={12} strokeWidth={1.9} />
        </Link>
      </div>
    </Section>
  );
}

function Opportunities() {
  return (
    <Section title="Opportunities" panel={false}>
      <p className="t-body leading-relaxed" style={{ color: "var(--text-4)" }}>
        Product Intelligence researches niches and candidate products against your own costs. Opportunities are not summarised here yet:
        open Products to run a discovery or read the latest research report.
      </p>
      <Link
        href="/dashboard/pi"
        className="mt-focus mt-3 inline-flex min-h-9 items-center sm:min-h-6 gap-1.5 t-body font-bold"
        style={{ color: "var(--text-3)" }}
      >
        Open Products <Icon name="arrow" size={12} strokeWidth={1.9} />
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
