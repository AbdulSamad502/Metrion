"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import { AgentCanvas } from "@/components/ceo/hub/AgentCanvas";
import { Conversation } from "@/components/ceo/hub/Conversation";
import { FindingsPanel } from "@/components/ceo/hub/FindingsPanel";
import { InvestigationList } from "@/components/ceo/hub/InvestigationList";
import { createCeoClient, type CeoClient } from "@/lib/ceo";
import { canvasNodes } from "@/lib/ceoModel";
import type { FeedFactory } from "@/lib/ceoPolling";
import { useCeoHub } from "@/lib/useCeoHub";

/** The real CEO Hub: the orchestration canvas on top, then investigations | conversation | findings.
 * Production wiring: the typed client over the signed-in user's Clerk token. */
export function CeoHub() {
  const { getToken } = useAuth();
  const client = useMemo(() => createCeoClient(getToken), [getToken]);
  return <CeoHubWorkspace client={client} />;
}

/** The workspace over an injected client (and, optionally, an injected findings feed), so it is testable without Clerk or a network.
 * The hub holds no orchestration logic: the backend classifies, validates, runs the specialists, synthesises and safety-gates. */
export function CeoHubWorkspace({ client, feedFactory, pollMs }: { client: CeoClient; feedFactory?: FeedFactory; pollMs?: number }) {
  const hub = useCeoHub(client, feedFactory, pollMs);
  const data = hub.detail.data;
  const nodes = canvasNodes(data?.agents ?? null, hub.availability, data?.investigation.status ?? null);

  return (
    <div className="flex flex-col gap-8" data-testid="ceo-hub">
      <section aria-labelledby="ceo-canvas">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="ceo-canvas" className="mt-eyebrow">
            Orchestration
          </h2>
          <p className="t-body-sm" style={{ color: "var(--text-5)" }}>
            A wire means the agent is attached to this investigation. Removing it stops new work from that agent; earlier findings stay as history.
          </p>
        </div>
        <div className="mt-panel" style={{ padding: "24px 20px" }}>
          {data ? (
            <AgentCanvas nodes={nodes} busy={hub.busyAgent} onToggle={hub.setAttached} />
          ) : (
            <p className="text-center t-body-sm" style={{ color: "var(--text-5)" }} data-testid="canvas-idle">
              Select or start an investigation to see which specialists are wired to it.
            </p>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-x-8 gap-y-8 xl:grid-cols-12">
        <aside className="xl:col-span-3" aria-label="Investigations">
          <InvestigationList
            status={hub.list.status}
            items={hub.list.items}
            error={hub.list.error}
            selectedId={hub.selectedId}
            showArchived={hub.showArchived}
            onToggleArchived={hub.setShowArchived}
            onSelect={hub.select}
            onCreate={hub.create}
            onRetry={hub.refreshList}
          />
        </aside>
        <main className="min-w-0 xl:col-span-5" aria-label="CEO conversation">
          <Conversation
            state={hub.state}
            detail={data}
            turn={hub.turn}
            notice={hub.notice}
            onDismissNotice={hub.dismissNotice}
            onSend={hub.sendTurn}
            onResolve={hub.resolve}
            onArchive={hub.archive}
            onRetry={() => void hub.retryDetail()}
          />
        </main>
        <aside className="min-w-0 xl:col-span-4" aria-label="Specialist findings">
          <FindingsPanel
            findings={data?.findings ?? []}
            messages={data?.messages ?? []}
            turns={data?.turns ?? []}
            agents={data?.agents ?? null}
            arrivedIds={hub.turn.arrivedIds}
            inFlightQuestion={hub.turn.question}
            processing={hub.state === "PROCESSING"}
          />
        </aside>
      </div>
    </div>
  );
}
