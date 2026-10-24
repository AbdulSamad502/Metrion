"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { AgentCard } from "@/components/ceo/AgentCard";
import { ErrorBanner, Pill } from "@/components/overview/parts";
import "@/components/overview/overview.css";
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
    <div className="ov mt-content">
      {error ? (
        <ErrorBanner message={error} onRetry={reload} />
      ) : !agents ? (
        <div className="ov-team" aria-label="Loading agents" role="status"><span className="sr-only">Loading agents…</span>{[0, 1, 2, 3].map((i) => <span key={i} className="ov-skel" style={{ height: 200, borderRadius: 24 }} />)}</div>
      ) : agents.length === 0 ? (
        <p className="ov-body">The backend returned no agents.</p>
      ) : (
        <ul className="ov-team ov-rise" style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {agents.map((a) => (
            <li key={a.id} style={{ display: "flex", minWidth: 0 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <AgentCard agent={a} lastActivity={a.id === "CI" && ci.summary ? ci.summary.lastResearchAt : undefined} />
              </div>
            </li>
          ))}
        </ul>
      )}

      <section className="ov-card ov-rise" style={{ ["--i" as string]: 2 }} aria-labelledby="ag-add">
        <h2 id="ag-add" className="ov-sr-only sr-only">Adding and removing agents</h2>
        <div className="ov-head-r" style={{ flexWrap: "wrap" }}>
          <span className="ov-title">Buying and removing agents</span>
          <Pill>Not available yet</Pill>
        </div>
        <p className="ov-body" style={{ maxWidth: "70ch" }}>
          No way to buy, add or remove agents yet. {agents && !error ? "The roster above is exactly what the backend reports — nothing on this page changes it." : "Nothing on this page changes the roster."}
        </p>
      </section>
    </div>
  );
}
