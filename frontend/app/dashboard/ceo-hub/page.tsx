"use client";

import Link from "next/link";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { AgentGraph, PipelineRail, type PipelineStage } from "@/components/ceo/OrchestrationDiagram";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { agentTier, useAgentRoster } from "@/lib/agents";
import { useShell } from "@/lib/ShellContext";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

/** What the CEO can really dispatch today — the fixed tool catalog in
 * `backend/src/backend/api/v1/ceo_hub.py`. Each one is a deterministic route, not a model
 * decision, and each is driven from the Competitor Intelligence workspace further down this page. */
const CEO_DISPATCHES = [
  { label: "Research a competitor now", detail: "Submit evidence for a tracked competitor and record a price snapshot." },
  { label: "Discover competitors", detail: "Search the allow-listed marketplaces for competing listings to review and accept." },
  { label: "Price-positioning scenario", detail: "Compare your price with a competitor's using the deterministic engine." },
];

export default function CeoHubPage() {
  return (
    <DashboardShell title="CEO Hub" subtitle="The command centre: question, orchestration, findings, action">
      <CeoHub />
    </DashboardShell>
  );
}

function CeoHub() {
  return (
    <div className="mt-content mt-stack">
      <Investigation />
      <Orchestration />
      <div className="grid grid-cols-1 gap-x-12 gap-y-10 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <Findings />
        </div>
        <div className="flex flex-col gap-10 xl:col-span-5">
          <Synthesis />
          <Actions />
        </div>
      </div>
      <CompetitorIntelligence />
    </div>
  );
}

/** The Competitor Intelligence workspace — competitor tracking, Research Now / Again, snapshot history,
 * price & availability events, listing diff, price-positioning scenario, competitor-vs-product
 * comparison, seller products, discovery, market overview and digest. The same component also backs
 * `/dashboard/competitors`, so there is one implementation and every API call is unchanged. */
function CompetitorIntelligence() {
  return (
    <section id="competitor-intelligence" aria-labelledby="ceo-ci" className="scroll-mt-6">
      <h2 id="ceo-ci" className="mt-eyebrow">
        Competitor Intelligence
      </h2>
      <p className="mt-2 mb-5 t-body-sm" style={{ color: "var(--text-5)" }}>
        Direct-execution tools the CEO dispatches to. Everything here runs against your own evidence and tracked competitors.
      </p>
      <CompetitorWorkspace />
    </section>
  );
}

/** TOP — the investigation context. The composer is real chrome but disabled: the backend has no
 * investigation/chat service, so there is nothing for it to submit to and nothing to attach agents to. */
function Investigation() {
  return (
    <section aria-labelledby="ceo-inv">
      <div className="flex items-center justify-between gap-3">
        <h2 id="ceo-inv" className="mt-eyebrow">
          Investigation
        </h2>
        <StatusBadge tone="neutral">Not available yet</StatusBadge>
      </div>
      <div
        className="mt-2.5 flex items-center gap-3 rounded-2xl px-4 py-3.5"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }}
      >
        <span style={{ color: "var(--text-7)" }}>
          <Icon name="ceo" size={20} />
        </span>
        <input
          disabled
          aria-label="Ask the CEO a question (not available yet)"
          placeholder="Ask the CEO — e.g. “Why did my margin drop last week?”"
          className="min-w-0 flex-1 cursor-not-allowed bg-transparent t-card-title outline-none"
          style={{ color: "var(--text-6)" }}
        />
        <button
          type="button"
          disabled
          className="flex h-9 w-9 flex-shrink-0 cursor-not-allowed items-center justify-center rounded-lg"
          style={{ border: "1px dashed var(--border-default)", color: "var(--text-7)" }}
          aria-label="Send (not available yet)"
        >
          <Icon name="arrow" size={15} />
        </button>
      </div>
      <p className="mt-2 t-body-sm" style={{ color: "var(--text-5)" }}>
        Conversational investigations need a backend investigation service that does not exist yet, so nothing can be asked,
        attached or replayed here. Each agent is driven from its own workspace — nothing on this page is simulated.
      </p>
    </section>
  );
}

function Orchestration() {
  const { agents, error, reload } = useAgentRoster();
  const { notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const wired = agents?.filter((a) => agentTier(a) === "connected").length ?? 0;
  const total = agents?.length ?? 0;
  const findingsKnown = n.alertsStatus !== "loading" && n.dataRequestsStatus !== "loading";
  const findings = alerts + requests;

  const stages: PipelineStage[] = [
    { key: "user", label: "You", title: "Ask", detail: "Free-text questions are not available yet.", state: "unavailable" },
    { key: "ceo", label: "CEO", title: "Plan & dispatch", detail: `${CEO_DISPATCHES.length} deterministic tools in its catalog.`, state: "live" },
    {
      key: "agents",
      label: "Specialist agents",
      title: agents ? `${wired} of ${total} wired` : "Loading…",
      detail: "Only wired agents are routed to by the CEO.",
      state: wired > 0 ? "live" : "idle",
    },
    {
      key: "findings",
      label: "Findings",
      title: !findingsKnown ? "Loading…" : findings === 0 ? "None right now" : `${findings} open`,
      detail: findingsKnown ? `${alerts} competitor ${alerts === 1 ? "alert" : "alerts"} · ${requests} CFO ${requests === 1 ? "request" : "requests"}` : "Reading the feed.",
      state: findings > 0 ? "live" : "idle",
    },
    { key: "synthesis", label: "Synthesis", title: "Combine findings", detail: "Needs the investigation service.", state: "unavailable" },
    { key: "action", label: "Action", title: "You decide", detail: "Recommend-only. Metrion never writes to a marketplace.", state: "live" },
  ];

  return (
    <Section title="Orchestration" panel={false}>
      <div className="flex flex-col gap-8">
        <PipelineRail stages={stages} />
        <div className="mt-panel" style={{ padding: "24px 20px" }}>
          {error ? (
            <ErrorNotice message={error} onRetry={reload} />
          ) : !agents ? (
            <LoadingState lines={4} label="Loading agents" />
          ) : agents.length === 0 ? (
            <EmptyState compact title="No agents reported" description="The backend returned an empty roster." />
          ) : (
            <AgentGraph agents={agents} />
          )}
        </div>
        <p className="-mt-3 t-body-sm" style={{ color: "var(--text-5)" }}>
          &ldquo;Wired to CEO&rdquo; is the backend&apos;s own flag. An agent that is not wired can still have a fully working
          workspace — open it directly.
        </p>
      </div>
    </Section>
  );
}

/** BOTTOM-left — what the specialists have found, from the real feeds. Source and next step on every row. */
function Findings() {
  const { notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest);
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const failed = [n.alertsError, n.dataRequestsError].filter((e): e is string => Boolean(e));
  const empty = n.alerts.length === 0 && requests.length === 0;

  return (
    <Section
      title="Agent findings"
      panel={false}
      action={
        !empty ? (
          <Link href="/dashboard/notifications" className="t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>
            See all <Icon name="arrow" size={12} strokeWidth={1.9} />
          </Link>
        ) : undefined
      }
    >
      {loading ? (
        <LoadingState lines={4} label="Loading findings" />
      ) : (
        <div className="flex flex-col gap-3">
          {failed.map((f, i) => (
            <ErrorNotice key={i} message={f} onRetry={n.reload} />
          ))}
          {empty && failed.length === 0 ? (
            <EmptyState
              compact
              icon="check"
              title="No findings"
              description={`No competitor alerts in the last ${ALERT_WINDOW_DAYS} days and no open CFO requests. Findings appear here as agents produce them.`}
            />
          ) : (
            <ul className="m-0 flex list-none flex-col p-0">
              {requests.slice(0, 3).map((r) => (
                <li key={r.id} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <Link href="/dashboard/cfo#anomalies" className="mt-row mt-focus flex items-start gap-3.5 rounded-lg px-1 py-3.5">
                    <span className="w-[72px] flex-shrink-0 pt-0.5">
                      <StatusBadge tone="warning">CFO</StatusBadge>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
                        Needs {r.requestedField}
                      </span>
                      <span className="block t-body-sm" style={{ color: "var(--text-5)" }}>
                        {r.reason ?? "No reason recorded."}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
              {n.alerts.slice(0, 5).map((a) => (
                <li key={a.priceEventId} style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <Link href="#competitor-intelligence" className="mt-row mt-focus flex items-start gap-3.5 rounded-lg px-1 py-3.5">
                    <span className="w-[72px] flex-shrink-0 pt-0.5">
                      <StatusBadge tone="info">CI</StatusBadge>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
                        {a.competitorLabel}
                      </span>
                      <span className="block t-body-sm" style={{ color: "var(--text-5)" }}>
                        {a.message}
                      </span>
                      {a.handoff.implication && (
                        <span className="mt-1 block t-body-sm" style={{ color: "var(--text-4)" }}>
                          Why it matters: {a.handoff.implication}
                        </span>
                      )}
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

function Synthesis() {
  return (
    <Section title="CEO synthesis" panel={false}>
      <div
        className="rounded-xl px-4 py-4"
        style={{ border: "1px dashed var(--connector-inactive)", background: "var(--bg-card-locked)" }}
        aria-disabled="true"
      >
        <div className="flex items-center gap-2.5">
          <span className="t-body font-semibold" style={{ color: "var(--text-5)" }}>
            Combined view across agents
          </span>
          <StatusBadge tone="neutral">Not available yet</StatusBadge>
        </div>
        <p className="mt-1.5 t-body-sm leading-relaxed" style={{ color: "var(--text-6)" }}>
          A single recommendation that weighs the CFO&apos;s and Competitor Intelligence&apos;s findings together needs the
          investigation service. Until then, read each finding on its own — they are never merged or summed for you.
        </p>
      </div>
    </Section>
  );
}

function Actions() {
  return (
    <Section title="What the CEO can dispatch" panel={false}>
      <ul className="m-0 flex list-none flex-col p-0">
        {CEO_DISPATCHES.map((d) => (
          <li key={d.label} className="flex items-start gap-3 py-3" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <span className="mt-0.5 flex-shrink-0" style={{ color: "var(--text-4)" }}>
              <Icon name="check" size={15} />
            </span>
            <span>
              <span className="block t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
                {d.label}
              </span>
              <span className="block t-body-sm" style={{ color: "var(--text-5)" }}>
                {d.detail}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <Link
        href="#competitor-intelligence"
        className="mt-btn mt-focus mt-4 inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 t-body font-bold"
        style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
      >
        Go to Competitor Intelligence <Icon name="arrow" size={13} strokeWidth={1.9} />
      </Link>
    </Section>
  );
}
