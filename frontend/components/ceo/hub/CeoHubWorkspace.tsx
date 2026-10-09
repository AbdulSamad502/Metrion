"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo, useState } from "react";
import { AgentsPanel } from "@/components/ceo/hub/AgentsPanel";
import { AgentStrip } from "@/components/ceo/hub/AgentStrip";
import { Composer } from "@/components/ceo/hub/Composer";
import { Conversation } from "@/components/ceo/hub/Conversation";
import { DecidePanel, type DecideKind } from "@/components/ceo/hub/DecidePanel";
import { FindingsPanel } from "@/components/ceo/hub/FindingsPanel";
import { HealthStrip } from "@/components/ceo/hub/HealthStrip";
import { InvestigationList } from "@/components/ceo/hub/InvestigationList";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { Icon } from "@/components/ui/Icon";
import { ApiError } from "@/lib/api";
import { createCeoClient, type AgentCode, type CeoClient, type UiAction } from "@/lib/ceo";
import { canvasNodes } from "@/lib/ceoModel";
import type { FeedFactory } from "@/lib/ceoPolling";
import { useCeoHub } from "@/lib/useCeoHub";

/** The real CEO Hub. Production wiring: the typed client over the signed-in user's Clerk token. */
export function CeoHub() {
  const { getToken } = useAuth();
  const client = useMemo(() => createCeoClient(getToken), [getToken]);
  return <CeoHubWorkspace client={client} />;
}

const agentOf = (action: string): AgentCode | null => ({ cfo: "CFO", ci: "CI", pi: "PI", cmo: "CMO" } as Record<string, AgentCode>)[action.split(".")[0]] ?? null;
const ACTION_WORDS: Record<string, string> = { pricing: "margin check", landed_cost: "landed cost", batch_size: "batch size", supplier_ranking: "supplier ranking", request_price_scenario: "price comparison", report: "report" };
const workLabel = (action: string) => `Working · ${ACTION_WORDS[action.split(".")[1] ?? ""] ?? (action.split(".")[1] ?? "").replace(/_/g, " ")}`;

/** One conversation. Top: the CEO and every agent. Right: the conversation. Left: the work behind the answers (each agent's results). Bottom: the chat bar.
 * The hub holds no orchestration logic: the backend classifies, validates, runs the specialists, synthesises and safety-gates. */
export function CeoHubWorkspace({ client, feedFactory, pollMs }: { client: CeoClient; feedFactory?: FeedFactory; pollMs?: number }) {
  const hub = useCeoHub(client, feedFactory, pollMs);
  const [drawer, setDrawer] = useState(false);
  const [form, setForm] = useState<DecideKind | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const data = hub.detail.data;
  // before any conversation exists, every agent the member can use is shown as ready (a new conversation attaches them all); locked / no-access ones still show as such
  const nodes = canvasNodes(data?.agents ?? { CI: true, CFO: true, PI: true, CMO: true }, hub.availability, data?.investigation.status ?? "ACTIVE", data?.findings ?? []);
  const processing = hub.state === "PROCESSING";
  const closed = hub.state === "RESOLVED" || hub.state === "ARCHIVED";
  const last = data?.messages[data.messages.length - 1];
  const needsInput = !!last && last.role === "CEO" && last.kind === "CLARIFICATION" && !closed;
  const workingByAgent: Partial<Record<AgentCode, string>> = {};
  for (const a of hub.turn.working) {
    const code = agentOf(a);
    if (code) workingByAgent[code] = workLabel(a);
  }

  /** Typing with no conversation open starts one: nobody should have to find a "new" button before asking. */
  const send = async (message: string, period: null, action: UiAction | null = null, clarification: Parameters<typeof hub.sendTurn>[3] = null, files: File[] = []) => {
    const conversation = hub.selectedId ?? (await hub.create((message || files[0]?.name || "Conversation").slice(0, 60)));
    if (!conversation) return;
    const ids: string[] = [];
    setUploadError(null);
    for (const f of files) {
      try {
        ids.push((await client.uploadAttachment(conversation, f)).id);
      } catch (e) {
        const code = e instanceof ApiError ? (e.detail as { code?: string } | null)?.code : undefined;
        setUploadError(
          code === "ATTACHMENTS_NOT_CONFIGURED" ? "Attachments are not set up yet by your operator, so nothing was sent."
            : code === "ATTACHMENT_TYPE_NOT_SUPPORTED" ? `${f.name} is not a supported file. Images, PDFs, CSV and Excel files can be attached. Nothing was sent.`
            : code === "ATTACHMENT_TOO_LARGE" ? `${f.name} is too large. Nothing was sent.`
            : `${f.name} could not be uploaded. Nothing was sent.`,
        );
        return;
      }
    }
    await hub.sendTurn(message || "Please read what I attached.", period, action, clarification, ids);
  };
  const empty = hub.state === "NO_SELECTION";
  /** Connect or remove an agent. With no conversation open one is started first (an agent is connected to a conversation, and a new one connects them all). */
  const toggleAgent = async (code: AgentCode, attach: boolean) => {
    if (!hub.selectedId && !(await hub.create("New conversation"))) return;
    await hub.setAttached(code, attach);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="ceo-hub" style={{ minHeight: "calc(100vh - 150px)" }}>
      <AgentStrip
        nodes={nodes} busy={hub.busyAgent} onToggle={(c, a) => void toggleAgent(c, a)} workingByAgent={workingByAgent}
        ceoWorking={processing ? hub.turn.stage ?? "Working…" : null} ceoNeedsInput={needsInput} hasConversation={!!hub.selectedId} onMenu={() => setDrawer(true)}
      />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-12" style={{ height: "calc(100vh - 330px)", minHeight: 420 }}>
        <section className="mt-panel min-h-[260px] min-w-0 overflow-y-auto p-4 lg:col-span-7" aria-label="Agent results" data-testid="work-area">
          <div className="flex flex-col gap-5">
            <AgentsPanel nodes={nodes} busy={hub.busyAgent} working={workingByAgent} onToggle={(c, attach) => void toggleAgent(c, attach)} />
            {data ? (
              <FindingsPanel
                findings={data.findings} messages={data.messages} turns={data.turns} agents={data.agents} arrivedIds={hub.turn.arrivedIds}
                inFlightQuestion={hub.turn.question} processing={processing} flows={hub.flows} onShowFlow={(id) => void hub.loadFlow(id)}
              />
            ) : (
              <p className="m-0 p-2 text-center t-body-sm" style={{ color: "var(--text-5)" }} data-testid="canvas-idle">
                What the agents find appears here, with the figures and where they came from.
              </p>
            )}
          </div>
        </section>

        <section className="mt-panel flex min-h-[320px] min-w-0 flex-col p-4 lg:col-span-5" aria-label="CEO conversation">
          {empty ? (
            <Welcome agents={{ CI: true, CFO: true, PI: true, CMO: true }} onAsk={(t) => void send(t, null)} onAction={(l, a) => void send(l, null, a)} onOpenForm={(f) => setForm(f as DecideKind)} />
          ) : (
            <Conversation
              onOpenForm={(f) => setForm(f as DecideKind)} state={hub.state} detail={data} turn={hub.turn} notice={hub.notice} onDismissNotice={hub.dismissNotice}
              onSend={hub.sendTurn} onResolve={hub.resolve} onReopen={hub.reopen} onArchive={hub.archive} onRetry={() => void hub.retryDetail()}
            />
          )}
        </section>
      </div>

      {form && (
        <div className="mx-auto w-full max-w-[1100px]">
          <DecidePanel client={client} kind={form} disabled={processing} onClose={() => setForm(null)} onRun={(label, action) => { void send(label, null, action); setForm(null); }} />
        </div>
      )}

      <div className="sticky bottom-0 pb-2 pt-1" style={{ background: "linear-gradient(to top, var(--bg-base) 70%, transparent)" }}>
        <Composer
          disabled={processing || closed}
          placeholder={closed ? "This conversation is closed. Reopen it to continue." : needsInput ? "Answer here, or pick an option above…" : "Ask anything about your business…"}
          onSend={(t, files) => void send(t, null, null, null, files)}
          error={uploadError}
        />
      </div>

      {drawer && (
        <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label="Conversations and business overview" data-testid="drawer">
          <div className="flex w-[min(420px,92vw)] flex-col gap-5 overflow-y-auto p-4" style={{ background: "var(--bg-base)", borderRight: "1px solid var(--border-subtle)" }}>
            <div className="flex items-center justify-between">
              <h2 className="m-0 t-card-title font-bold" style={{ color: "var(--text-1)" }}>Conversations</h2>
              <button type="button" aria-label="Close" onClick={() => setDrawer(false)} className="mt-btn mt-focus rounded-lg p-1.5" style={{ color: "var(--text-3)" }}><Icon name="close" size={16} /></button>
            </div>
            <InvestigationList
              status={hub.list.status} items={hub.list.items} error={hub.list.error} selectedId={hub.selectedId} showArchived={hub.showArchived}
              onToggleArchived={hub.setShowArchived} onSelect={(id) => { hub.select(id); setDrawer(false); }} onCreate={(t) => { void hub.create(t); setDrawer(false); }} onRetry={hub.refreshList}
            />
            <section aria-labelledby="ceo-health">
              <h3 id="ceo-health" className="mb-2 mt-eyebrow">Business at a glance</h3>
              <HealthStrip health={hub.health} onRefresh={() => void hub.refreshHealth()} />
            </section>
          </div>
          <button type="button" aria-label="Close panel" className="flex-1" style={{ background: "rgba(0,0,0,0.45)" }} onClick={() => setDrawer(false)} />
        </div>
      )}
    </div>
  );
}
