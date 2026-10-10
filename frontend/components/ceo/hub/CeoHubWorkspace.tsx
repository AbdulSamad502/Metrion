"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo, useState } from "react";
import { AgentCanvas } from "@/components/ceo/hub/AgentCanvas";
import { Composer } from "@/components/ceo/hub/Composer";
import { Conversation } from "@/components/ceo/hub/Conversation";
import { DecidePanel, type DecideKind } from "@/components/ceo/hub/DecidePanel";
import { FindingsPanel } from "@/components/ceo/hub/FindingsPanel";
import { HealthStrip } from "@/components/ceo/hub/HealthStrip";
import { InvestigationList } from "@/components/ceo/hub/InvestigationList";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { MemoryPanel } from "@/components/ceo/hub/MemoryPanel";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api";
import { createCeoClient, type AgentCode, type CeoClient, type UiAction } from "@/lib/ceo";
import { canvasNodes, QUICK_ACTIONS, quickActionState } from "@/lib/ceoModel";
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

  const ceoTone = needsInput ? "input" : processing ? "working" : "idle";
  const ceoStatus = needsInput ? "Needs your input" : processing ? hub.turn.stage ?? "Working…" : hub.selectedId ? "Ready" : "Start a conversation";
  const connected = nodes.filter((n) => n.state === "ATTACHED");
  const quick = QUICK_ACTIONS.filter((q) => ["pnl", "research", "competitors"].includes(q.id));

  return (
    <div className="grid gap-3 lg:grid-cols-12" data-testid="ceo-hub" style={{ minHeight: "calc(100vh - 150px)" }}>
      {/* LEFT: the orchestration — the CEO and its agents on wires. Remove or connect an agent right on its wire. */}
      <section className="mt-panel flex min-w-0 flex-col gap-4 p-4 lg:col-span-7" aria-label="Agent orchestration" data-testid="work-area" style={{ maxHeight: "calc(100vh - 150px)", overflowY: "auto" }}>
        <header className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="m-0 t-card-title font-bold" style={{ color: "var(--text-1)" }}>Agent orchestration</h2>
            <p className="m-0 mt-0.5 t-meta" style={{ color: "var(--text-5)" }}>
              {data ? `Conversation · ${new Date(data.investigation.created_at).toLocaleDateString()}` : "Remove or connect agents here; a new conversation starts with all of them connected."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {data && <StatusBadge tone={data.investigation.status === "ACTIVE" ? "accent" : "neutral"} dot={data.investigation.status === "ACTIVE"}>{data.investigation.status === "ACTIVE" ? "Active" : data.investigation.status.toLowerCase()}</StatusBadge>}
            <button type="button" onClick={() => setDrawer(true)} aria-label="Conversations and business overview" data-testid="open-drawer" className="mt-btn mt-focus flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)" }}>
              <Icon name="menu" size={14} /> Conversations
            </button>
          </div>
        </header>

        <AgentCanvas
          nodes={nodes} busy={hub.busyAgent} onToggle={(c, attach) => void toggleAgent(c, attach)}
          working={workingByAgent} ceoStatus={ceoStatus} ceoTone={ceoTone}
        />

        <ul className="m-0 flex list-none flex-wrap items-center gap-x-4 gap-y-1 p-0 t-meta" style={{ color: "var(--text-5)" }} aria-label="Legend">
          <li className="flex items-center gap-1.5"><span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--positive)" }} /> Connected</li>
          <li className="flex items-center gap-1.5"><span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} /> Working</li>
          <li className="flex items-center gap-1.5"><span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--warning)" }} /> Needs your input</li>
          <li className="flex items-center gap-1.5"><span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--text-6)" }} /> Removed or locked</li>
        </ul>

        {data ? (
          <FindingsPanel
            findings={data.findings} messages={data.messages} turns={data.turns} agents={data.agents} arrivedIds={hub.turn.arrivedIds}
            inFlightQuestion={hub.turn.question} processing={processing} flows={hub.flows} onShowFlow={(id) => void hub.loadFlow(id)}
            onAsk={closed ? undefined : (t) => void send(t, null)}
          />
        ) : (
          <p className="m-0 p-2 text-center t-body-sm" style={{ color: "var(--text-5)" }} data-testid="canvas-idle">
            What the agents find appears here, with the figures and where they came from.
          </p>
        )}
        <section aria-labelledby="ceo-health-inline">
          <h3 id="ceo-health-inline" className="mb-2 mt-eyebrow">Business at a glance</h3>
          <HealthStrip health={hub.health} onRefresh={() => void hub.refreshHealth()} />
        </section>
        <MemoryPanel items={hub.memory} onForget={(id) => void hub.forgetMemory(id)} />
      </section>

      {/* RIGHT: the conversation, quick actions, who is connected, and the chat bar. */}
      <section className="mt-panel flex min-h-[420px] min-w-0 flex-col gap-3 p-4 lg:col-span-5" aria-label="CEO conversation" style={{ height: "calc(100vh - 150px)" }}>
        <header className="flex items-center gap-3 pb-1" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          <span className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: "var(--fill-hover)", color: "var(--accent)" }}><Icon name="ceo" size={18} /></span>
          <div className="min-w-0">
            <div className="t-body font-bold" style={{ color: "var(--text-1)" }}>CEO</div>
            <div className="t-meta" style={{ color: "var(--text-5)" }}>Your AI business co-pilot</div>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {empty ? (
            <Welcome agents={{ CI: true, CFO: true, PI: true, CMO: true }} onAsk={(t) => void send(t, null)} onAction={(l, a) => void send(l, null, a)} onOpenForm={(f) => setForm(f as DecideKind)} />
          ) : (
            <Conversation
              onOpenForm={(f) => setForm(f as DecideKind)} state={hub.state} detail={data} turn={hub.turn} needs={hub.needs} notice={hub.notice} onDismissNotice={hub.dismissNotice}
              onSend={hub.sendTurn} onResolve={hub.resolve} onReopen={hub.reopen} onArchive={hub.archive} onRetry={() => void hub.retryDetail()}
            />
          )}
        </div>

        {form && (
          <DecidePanel client={client} kind={form} disabled={processing} onClose={() => setForm(null)} onRun={(label, action) => { void send(label, null, action); setForm(null); }} />
        )}

        {!empty && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Quick actions" data-testid="quick-row">
            {quick.map((q) => {
              const st = quickActionState(q, data?.agents ?? null, null);
              return (
                <button key={q.id} type="button" disabled={!st.enabled || processing || closed} title={st.reason ?? undefined} onClick={() => void send(q.label, null, q.action)}
                  className="mt-chip mt-focus rounded-full px-2.5 py-1 t-meta" style={{ color: "var(--text-3)", border: "1px solid var(--border-subtle)", opacity: st.enabled ? 1 : 0.45 }}>
                  {q.label}
                </button>
              );
            })}
            <button type="button" disabled={processing || closed} onClick={() => void send("Should I stock a new product?", null, { kind: "PLAYBOOK", key: "NEW_PRODUCT_DECISION" })}
              className="mt-chip mt-focus rounded-full px-2.5 py-1 t-meta" style={{ color: "var(--text-3)", border: "1px solid var(--border-subtle)" }}>
              New product decision
            </button>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 t-meta" style={{ color: "var(--text-5)" }} data-testid="connected-row">
          <span className="flex items-center gap-1.5">
            {connected.map((n) => (
              <span key={n.code} title={n.name} className="flex h-6 w-6 items-center justify-center rounded-full font-bold" style={{ background: "var(--fill-hover)", color: "var(--text-2)", fontSize: 10 }}>{n.code}</span>
            ))}
          </span>
          <span>{connected.length}/{nodes.length} agents connected</span>
        </div>

        <Composer
          disabled={processing || closed}
          placeholder={closed ? "This conversation is closed. Reopen it to continue." : needsInput ? "Answer here, or pick an option above…" : "Ask the CEO anything…"}
          onSend={(t, files) => void send(t, null, null, null, files)}
          error={uploadError}
        />
      </section>

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
          </div>
          <button type="button" aria-label="Close panel" className="flex-1" style={{ background: "rgba(0,0,0,0.45)" }} onClick={() => setDrawer(false)} />
        </div>
      )}
    </div>
  );
}
