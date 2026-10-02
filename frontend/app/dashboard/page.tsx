"use client";

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
import { agentMeta, agentTier, useAgentRoster } from "@/lib/agents";
import { useCiSummary } from "@/lib/useCiSummary";
import { useShell } from "@/lib/ShellContext";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

/** The post-auth landing screen. Reading order is the point:
 *   1. Business state   — one sentence and four real counts
 *   2. What matters now — the things that need a decision, each with its next step
 *   3. Financial impact — where profit lives (there is no honest single number to show here)
 *   4. Agent activity   — who is working, and what they last did
 *
 * Every figure comes from a real response (`/ci/summary`, the shared notifications feed,
 * `/ceo-hub/agents`). There is deliberately NO headline profit number: the backend has no
 * portfolio-level profit endpoint, and computing money in the browser breaks the project's hard
 * rule. Where data does not exist the page says so and points at the screen that produces it. */
export default function DashboardPage() {
  return (
    <DashboardShell
      title="Overview"
      subtitle="What is happening, what matters, and what to do next"
      context={<HeaderContext kind="both" />}
    >
      <Overview />
    </DashboardShell>
  );
}

function Overview() {
  const ci = useCiSummary();
  return (
    <div className="mt-content mt-stack">
      <BusinessState ci={ci} />
      <div className="grid grid-cols-1 gap-x-12 gap-y-10 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <WhatMattersNow />
        </div>
        <div className="flex flex-col gap-10 xl:col-span-5">
          <FinancialImpact />
          <Opportunities />
        </div>
      </div>
      <AgentActivity lastResearchAt={ci.summary?.lastResearchAt} />
    </div>
  );
}

function BusinessState({ ci }: { ci: ReturnType<typeof useCiSummary> }) {
  const { displayName, notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const total = requests + alerts;
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const { summary } = ci;

  return (
    <section aria-labelledby="ov-state">
      <div className="mt-eyebrow">Welcome back, {displayName.split(" ")[0]}</div>
      <h2 id="ov-state" className="t-headline mt-2" style={{ color: "var(--text-1)" }}>
        {loading ? (
          <span className="mt-skeleton inline-block h-8 w-80 max-w-full align-middle" aria-label="Loading your summary" />
        ) : total === 0 ? (
          "Nothing needs your attention right now."
        ) : (
          `${total} ${total === 1 ? "thing needs" : "things need"} your attention.`
        )}
      </h2>
      {!loading && (
        <p className="t-body mt-1.5 max-w-[70ch]" style={{ color: "var(--text-4)" }}>
          {total === 0
            ? `No competitor alerts in the last ${ALERT_WINDOW_DAYS} days and no open data requests. Upload a settlement or order report in CFO to keep the picture current.`
            : [
                requests > 0 ? `${requests} data ${requests === 1 ? "request" : "requests"} from the CFO` : null,
                alerts > 0 ? `${alerts} competitor ${alerts === 1 ? "alert" : "alerts"} in the last ${ALERT_WINDOW_DAYS} days` : null,
              ]
                .filter(Boolean)
                .join(" · ")}
        </p>
      )}

      {ci.error ? (
        <div className="mt-6">
          <ErrorNotice message={ci.error} />
        </div>
      ) : ci.forbidden ? null : (
        <div
          className="mt-6 grid grid-cols-2 lg:grid-cols-4 lg:divide-x"
          style={{ borderTop: "1px solid var(--border-subtle)", borderBottom: "1px solid var(--border-subtle)", ["--tw-divide-color" as string]: "var(--border-subtle)" }}
        >
          <Stat
            label="Competitors tracked"
            href="/dashboard/competitors"
            loading={!summary}
            value={summary ? String(summary.trackedCompetitors) : null}
            hint={
              summary && summary.trackedCompetitors === 0 ? (
                "Add your first competitor"
              ) : summary?.lastResearchAt ? (
                `Last research ${new Date(summary.lastResearchAt).toLocaleDateString()}`
              ) : (
                "No research run yet"
              )
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
    </section>
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
          <Link href="/dashboard/notifications" className="t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
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
          {rows === 0 && failed.length === 0 ? (
            <EmptyState
              compact
              icon="check"
              title="You're clear"
              description="When a competitor changes price or the CFO needs an input from you, it appears here with the next step."
            />
          ) : (
            <ul className="m-0 flex list-none flex-col p-0">
              {requests.slice(0, 4).map((r) => (
                <li key={r.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
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
                <li key={a.priceEventId} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
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

function FinancialImpact() {
  return (
    <Section title="Financial impact" panel={false}>
      <div className="mt-panel flex flex-col gap-4" style={{ background: "var(--bg-card-elevated)" }}>
        <p className="t-body-lg leading-relaxed" style={{ color: "var(--text-3)" }}>
          Contribution profit is computed per period by the CFO engine from the reports you upload, and each figure carries the
          source it came from. There is no single headline number here, because it would hide which period and which data it
          came from.
        </p>
        <div className="flex flex-wrap gap-2.5">
          <Link
            href="/dashboard/cfo#profitability"
            className="mt-btn mt-focus inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 t-body font-bold"
            style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
          >
            View profitability <Icon name="arrow" size={13} strokeWidth={1.9} />
          </Link>
          <Link
            href="/dashboard/cfo#import"
            className="mt-btn mt-focus inline-flex items-center rounded-lg px-3.5 py-2 t-body font-semibold"
            style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}
          >
            Upload reports
          </Link>
        </div>
      </div>
    </Section>
  );
}

function Opportunities() {
  return (
    <Section title="Opportunities" panel={false}>
      <p className="t-body leading-relaxed" style={{ color: "var(--text-4)" }}>
        Nothing has been surfaced yet. Product Intelligence finds niches and candidates against your own costs — run a
        discovery to see what is worth pursuing.
      </p>
      <Link
        href="/dashboard/pi"
        className="mt-3 inline-flex items-center gap-1.5 t-body font-bold"
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
        <Link href="/dashboard/ceo-hub" className="t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
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
                <th aria-label="Open" />
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
                        {tier === "connected" ? "Wired to CEO" : tier === "available" ? "Workspace only" : "Not built yet"}
                      </StatusBadge>
                    </td>
                    <td style={{ color: "var(--text-4)" }}>{last}</td>
                    <td className="text-right">
                      {meta.href && (
                        <Link href={meta.href} className="mt-focus t-body-sm font-bold" style={{ color: "var(--text-3)" }}>
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
