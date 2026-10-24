"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { AgentCard } from "@/components/ceo/AgentCard";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAgentRoster } from "@/lib/agents";
import { useCiSummary } from "@/lib/useCiSummary";

export default function AgentsPage() {
  return (
    <DashboardShell {...PAGE_COPY["agents"]}>
      <Agents />
    </DashboardShell>
  );
}

function Agents() {
  const { agents, error, reload } = useAgentRoster();
  const ci = useCiSummary();
  return (
    <div className="mt-content mt-stack mt-pure-black">
      {error ? (
        <ErrorNotice message={error} onRetry={reload} />
      ) : !agents ? (
        <LoadingState lines={4} label="Loading agents" />
      ) : agents.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--text-6)" }}>
          The backend returned no agents.
        </div>
      ) : (
        <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 xl:grid-cols-4">
          {agents.map((a) => (
            <li key={a.id}>
              <AgentCard agent={a} lastActivity={a.id === "CI" && ci.summary ? ci.summary.lastResearchAt : undefined} />
            </li>
          ))}
        </ul>
      )}

      <Section title="Adding and removing agents" panel={false}>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="t-body-lg font-semibold" style={{ color: "var(--text-3)" }}>
            Buying and removing agents
          </span>
          <StatusBadge tone="neutral">Not available yet</StatusBadge>
        </div>
        <p className="mt-2 max-w-[70ch] t-body leading-relaxed" style={{ color: "var(--text-4)" }}>
          There is no way to buy, add or remove agents in Metrion yet. {agents && !error ? "The roster above is exactly what the backend reports — nothing on this page changes it." : "Nothing on this page changes the roster."}
        </p>
      </Section>
    </div>
  );
}
