"use client";

import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { AgentCanvas } from "@/components/ceo/hub/AgentCanvas";
import { Composer, type FileStatus } from "@/components/ceo/hub/Composer";
import { Conversation } from "@/components/ceo/hub/Conversation";
import { DecidePanel, type DecideKind } from "@/components/ceo/hub/DecidePanel";
import { ExecutionPanel } from "@/components/ceo/hub/ExecutionPanel";
import { FindingsPanel } from "@/components/ceo/hub/FindingsPanel";
import { HealthStrip } from "@/components/ceo/hub/HealthStrip";
import "./ceo.css";
import { useDotSpotlight } from "@/components/ceo/hub/useDotSpotlight";
import { InvestigationList } from "@/components/ceo/hub/InvestigationList";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { MemoryPanel } from "@/components/ceo/hub/MemoryPanel";
import { SharedFindingsPanel } from "@/components/ceo/hub/SharedFindingsPanel";
import { RecentDecisions } from "@/components/ceo/hub/RecentDecisions";
import { useFrame } from "@/components/dashboard/ShellFrame";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { ApiError } from "@/lib/api";
import { createCeoClient, type AgentCode, type CeoClient, type UiAction } from "@/lib/ceo";
import { canvasNodes, QUICK_ACTIONS, quickActionState } from "@/lib/ceoModel";
import type { FeedFactory } from "@/lib/ceoPolling";
import { draftFromParams } from "@/lib/ciWorkspace";
import { useCeoHub } from "@/lib/useCeoHub";
import { useModalFocus } from "@/lib/useModalFocus";

/** The real CEO Hub. Production wiring: the typed client over the signed-in user's Clerk token. */
export function CeoHub() {
  const { getToken } = useAuth();
  const client = useMemo(() => createCeoClient(getToken), [getToken]);
  // A link from another page can open a decision form directly (e.g. Products → /dashboard/ceo-hub?form=new-product); anything else is ignored.
  const params = useSearchParams();
  const initialForm = FORM_LINKS[params.get("form") ?? ""] ?? null;
  // The Competitors page's shortcuts open the hub with a draft message (`?ask=research&about=<product>`); the seller sends it, nothing runs on arrival (CI spec D14).
  const initialDraft = draftFromParams(params.get("ask"), params.get("about"));
  const rawFinding = params.get("finding");
  const initialFindingId = params.get("ask") === "finding" && rawFinding && /^[0-9a-f-]{36}$/i.test(rawFinding) ? rawFinding : null; // an id only; the server validates it for this tenant
  return <CeoHubWorkspace client={client} initialForm={initialForm} initialDraft={initialDraft} initialFindingId={initialFindingId} />;
}

const FORM_LINKS: Record<string, DecideKind> = { "new-product": "NEW_PRODUCT_DECISION", "price-impact": "COMPETITOR_PRICE_IMPACT" };

const agentOf = (action: string): AgentCode | null => ({ cfo: "CFO", ci: "CI", pi: "PI", cmo: "CMO" } as Record<string, AgentCode>)[action.split(".")[0]] ?? null;
const ACTION_WORDS: Record<string, string> = { pricing: "margin check", landed_cost: "landed cost", batch_size: "batch size", supplier_ranking: "supplier ranking", request_price_scenario: "price comparison", report: "report" };
const workLabel = (action: string) => `Working · ${ACTION_WORDS[action.split(".")[1] ?? ""] ?? (action.split(".")[1] ?? "").replace(/_/g, " ")}`;

/** One conversation, two columns (the reference layout). Left: the CEO and its agents on wires, what is running now (from the live event stream) and the
 * work behind the answers. Right, and wider: the conversation, with the chat bar fixed at the bottom of its own column. Below the desktop breakpoint the
 * two are tabs, so the conversation is never squeezed. The hub holds no orchestration logic: the backend classifies, validates, runs the specialists,
 * synthesises and safety-gates. */
export function CeoHubWorkspace({ client, feedFactory, pollMs, initialForm = null, initialDraft = null, initialFindingId = null }: { client: CeoClient; feedFactory?: FeedFactory; pollMs?: number; initialForm?: DecideKind | null; initialDraft?: string | null; initialFindingId?: string | null }) {
  const hub = useCeoHub(client, feedFactory, pollMs);
  const findingForFirstSend = useRef<string | null>(initialFindingId); // carried by the first message only, then dropped
  const frame = useFrame();
  const rootRef = useRef<HTMLDivElement | null>(null);
  useDotSpotlight(rootRef);
  const [drawer, setDrawer] = useState(false);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  useModalFocus(drawer, drawerRef, () => setDrawer(false)); // a real modal: focus in, Tab contained, Escape closes, focus back to the opener
  const [form, setForm] = useState<DecideKind | null>(initialForm);
  const [uploadError, setUploadError] = useState<string | null>(null);
  /** Per file (identity: name, size, modified time): where it is in the upload. A file already attached to this conversation is never uploaded twice on a retry. */
  const [fileStates, setFileStates] = useState<Record<string, FileStatus>>({});
  const [fileInfos, setFileInfos] = useState<Record<string, string>>({});
  const uploadedIds = useRef(new Map<string, string>());
  const fileKey = (f: File) => `${f.name}|${f.size}|${f.lastModified}`;
  const setFileState = (f: File, st: FileStatus) => setFileStates((m) => ({ ...m, [fileKey(f)]: st }));
  /** The hub shows ONE view at a time, full width: the agents (the live canvas), the conversation, or the activity / results. All three stay mounted; the chat bar is always at the bottom. */
  const [view, setView] = useState<"agents" | "chat">("chat");
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
  // An agent the CEO has routed this turn to is lit from the moment it is chosen, not only while a specialist leg runs (a saved-result read has no leg).
  for (const a of hub.turn.called ?? []) {
    const code = agentOf(a);
    if (code && !workingByAgent[code]) workingByAgent[code] = "Working…";
  }

  /** Typing with no conversation open starts one: nobody should have to find a "new" button before asking. */
  const send = async (message: string, period: null, action: UiAction | null = null, clarification: Parameters<typeof hub.sendTurn>[3] = null, files: File[] = []): Promise<boolean> => {
    const conversation = hub.selectedId ?? (await hub.create((message || files[0]?.name || "Conversation").slice(0, 60)));
    if (!conversation) return false;
    const ids: string[] = [];
    setUploadError(null);
    for (const f of files) {
      const known = uploadedIds.current.get(`${conversation}|${fileKey(f)}`);
      if (known) { ids.push(known); setFileState(f, "uploaded"); continue; }
      setFileState(f, "uploading");
      try {
        const up = await client.uploadAttachment(conversation, f);
        const id = up.id;
        uploadedIds.current.set(`${conversation}|${fileKey(f)}`, id);
        setFileState(f, "uploaded");
        const table = up.table;
        if (table?.status === "READ") {
          const names = table.sheets.map((sh) => sh.name).filter((n) => n !== "(CSV)");
          const rows = table.sheets.reduce((n, sh) => n + sh.rows, 0);
          const cut = table.sheetsTruncated || table.sheets.some((sh) => sh.truncated);
          setFileInfos((m) => ({ ...m, [fileKey(f)]: `${names.length > 0 ? `${names.join(", ")} · ` : ""}${rows} rows read${cut ? " (limit reached: not all rows were read)" : ""}` }));
        } else if (table?.status === "UNREADABLE") {
          setFileInfos((m) => ({ ...m, [fileKey(f)]: `Could not be read as a table: ${table.note}` }));
        }
        ids.push(id);
      } catch (e) {
        setFileState(f, "failed");
        const code = e instanceof ApiError ? (e.detail as { code?: string } | null)?.code : undefined;
        setUploadError(
          code === "ATTACHMENTS_NOT_CONFIGURED" ? "Attachments are not switched on for this server. An administrator must set CEO_ATTACHMENT_MAX_BYTES, CEO_ATTACHMENT_MAX_FILES and CEO_ATTACHMENT_MAX_PAGES and restart the backend. Nothing was sent."
            : code === "ATTACHMENT_TYPE_NOT_SUPPORTED" ? `${f.name} is not a supported file. Images, PDFs, CSV and Excel files can be attached. Nothing was sent.`
            : code === "ATTACHMENT_TOO_LARGE" ? `${f.name} is too large. Nothing was sent.`
            : code === "INVESTIGATION_NOT_ACTIVE" ? "This conversation is closed, so files cannot be attached. Nothing was sent."
            : `${f.name} could not be uploaded. Nothing was sent; your message and files are still here to retry.`,
        );
        return false;
      }
    }
    const findingId = findingForFirstSend.current;
    findingForFirstSend.current = null;
    void hub.sendTurn(message || "Please read what I attached.", period, action, clarification, ids, findingId); // the turn reports its own progress and errors; the composer must not wait for the whole answer
    return true;
  };
  const empty = hub.state === "NO_SELECTION";
  /** Connect or remove an agent. With no conversation open one is started first (an agent is connected to a conversation, and a new one connects them all). */
  const toggleAgent = async (code: AgentCode, attach: boolean) => {
    if (!hub.selectedId && !(await hub.create("New conversation"))) return;
    await hub.setAttached(code, attach);
  };

  const waiting = hub.awaitingAnswer && !closed;
  const ceoTone = needsInput ? "input" : processing || waiting ? "working" : "idle";
  const ceoStatus = needsInput ? "Needs your input" : processing ? hub.turn.stage ?? "Working…" : waiting ? "Answering your last question…" : hub.selectedId ? "Ready" : "Start a conversation";
  const canvas = (
    <AgentCanvas
      nodes={nodes} busy={hub.busyAgent} onToggle={(c, attach) => void toggleAgent(c, attach)}
      working={workingByAgent} ceoStatus={ceoStatus} ceoTone={ceoTone}
    />
  );
  const connected = nodes.filter((n) => n.state === "ATTACHED");
  const quick = QUICK_ACTIONS.filter((q) => ["pnl", "research", "competitors"].includes(q.id));
  const tabBtn = (id: "agents" | "chat", label: string, testId: string) => (
    <button key={id} type="button" role="tab" aria-selected={view === id} data-testid={testId} onClick={(e) => { setView(id); e.currentTarget.scrollIntoView?.({ inline: "center", block: "nearest" }); }}
      className="mt-focus ceo-tab min-h-[40px] whitespace-nowrap px-3 t-body-sm font-semibold" data-on={view === id}>
      {label}
    </button>
  );

  const activity = (
    <>
          {(!!hub.selectedId || processing || needsInput || hub.awaitingAnswer) && <ExecutionPanel
            state={hub.state} needsInput={needsInput} turn={hub.turn} turns={data?.turns ?? []} awaitingAnswer={hub.awaitingAnswer}
            working={(Object.entries(workingByAgent) as [AgentCode, string][]).map(([code, label]) => ({ code, label }))}
          />}

          {data && (data.findings.length > 0 || processing) && (
            <FindingsPanel
              findings={data.findings} messages={data.messages} turns={data.turns} agents={data.agents} arrivedIds={hub.turn.arrivedIds}
              inFlightQuestion={hub.turn.question} processing={processing} flows={hub.flows} onShowFlow={(id) => void hub.loadFlow(id)}
              onAsk={closed ? undefined : (t) => void send(t, null)}
            />
          )}
          {hub.memory.length > 0 && <MemoryPanel items={hub.memory} onForget={(id) => void hub.forgetMemory(id)} />}
          {((hub.shared.status === "error" && !hub.shared.data) || ((hub.shared.data?.items.length ?? 0) > 0 || (hub.shared.data?.hiddenTotal ?? 0) > 0)) && <SharedFindingsPanel state={hub.shared} onForget={(id) => void hub.forgetShared(id)} onRetry={() => void hub.refreshShared()} />}
    </>
  );

  const conversationLabel = processing ? "Conversation · live" : needsInput ? "Conversation · waiting" : "Conversation";
  return (
    <div ref={rootRef} data-view={view} className="mt-galaxy ceo-root flex flex-col gap-3 xl:h-full" data-testid="ceo-hub">
      <div className="ceo-dots" aria-hidden />
      {/* The conversation list could never be loaded (nothing is shown from earlier): the backend is unreachable or refused. Said once, here, with a retry, instead of a screen that looks like a normal empty start. When an earlier list is on screen, the existing "could not refresh" notice covers it instead (no second message). */}
      {hub.list.status === "error" && hub.list.items.length === 0 && (
        <div data-testid="hub-unavailable"><ErrorNotice message={`Your conversations could not be loaded. ${hub.list.error ?? ""}`.trim()} onRetry={hub.refreshList} /></div>
      )}

      {/* TOP BAR: the navigation on the left; the three views in the middle (agents, conversation, activity and results); new chat and history on the right. No boxes. */}
      <header className="ceo-top flex flex-shrink-0 items-center gap-2">
        {frame && (
          <button type="button" onClick={frame.openMenu} aria-label="Open navigation" title="Open navigation" data-testid="hub-menu-button" className="ceo-icon mt-focus">
            <Icon name="menu" size={18} />
          </button>
        )}
        <div className="ceo-tabs flex min-w-0 flex-1 items-center justify-center overflow-x-auto" role="tablist" aria-label="Agents, conversation, or activity and results">
          {tabBtn("agents", "Agents", "tab-agents")}
          {tabBtn("chat", conversationLabel, "right-tab-chat")}
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <button type="button" data-testid="new-investigation" disabled={processing || empty} onClick={() => { hub.select(null); setView("chat"); }} aria-label="New chat" title={empty ? "You are already on a new chat: type below to start it." : "Start a new chat"} className="ceo-action mt-focus">
            <Icon name="plus" size={16} strokeWidth={2} /> <span className="max-sm:sr-only">New chat</span>
          </button>
          <button type="button" onClick={() => setDrawer(true)} aria-label="Conversations and business overview" title="Chat history" data-testid="open-drawer" className="ceo-action mt-focus">
            <Icon name="history" size={16} /> <span className="max-sm:sr-only">History</span>
          </button>
        </div>
      </header>

      {/* ONE view fills the screen under the bar; the chat bar below it never moves. */}
      <div className="flex min-h-[55dvh] min-w-0 flex-col xl:min-h-0 xl:flex-1">
        <section className={`min-h-0 min-w-0 flex-1 overflow-y-auto ${view === "agents" ? "flex flex-col" : "hidden"}`} aria-label="Specialists" data-testid="work-area">
          <h2 className="sr-only">Your specialists</h2>
          {canvas}
        </section>

        <section className={`min-h-0 min-w-0 flex-1 flex-col overflow-y-auto max-xl:flex-none max-xl:overflow-visible ${view === "chat" ? "flex" : "hidden"}`} aria-label="CEO conversation" data-testid="chat-column">
          <div className="ceo-read ceo-split mx-auto flex w-full max-w-[820px] flex-1 flex-col gap-3">
            <div className="ceo-conv flex min-w-0 flex-1 flex-col gap-3">
            <div className="truncate t-meta" style={{ color: needsInput ? "var(--warning)" : "var(--text-5)" }} data-testid="chat-status">{ceoStatus}</div>
            {empty ? (
              <Welcome agents={{ CI: true, CFO: true, PI: true, CMO: true }} onAsk={(t) => void send(t, null)} onAction={(l, a) => void send(l, null, a)} onOpenForm={(f) => setForm(f as DecideKind)} />
            ) : (
              <Conversation
                onOpenForm={(f) => setForm(f as DecideKind)} state={hub.state} detail={data} turn={hub.turn} needs={hub.needs} notice={hub.notice} onDismissNotice={hub.dismissNotice}
                onSend={hub.sendTurn} loadAttachmentImage={(inv, att) => client.getAttachmentImage(inv, att)} approveListing={(id) => client.approveListing(id)} historyApi={client.historyApi} performanceApi={client.performanceApi} recordListingCopy={(id) => client.recordListingCopy(id)} awaiting={hub.awaitingAnswer} onApprovePlan={(id, h) => void hub.approvePlan(id, h)} onDeclinePlan={(id) => void hub.declinePlan(id)} planBusy={hub.planBusy} onResolve={hub.resolve} onReopen={hub.reopen} onArchive={hub.archive} onRetry={() => void hub.retryDetail()}
              />
            )}
            </div>
          <div className="ceo-activity flex flex-col gap-6 pb-6" data-testid="results-area" aria-label="Activity and results" role="region">
            <h2 className="m-0 mt-eyebrow">Activity &amp; results</h2>
            {(hub.health.entries.length > 0 || hub.health.status === "error" || hub.list.items.length > 0) && <div className="@container"><div className="grid grid-cols-1 gap-3 @[760px]:grid-cols-2" data-testid="summary-cards">
              <section aria-labelledby="ceo-health-inline" className="flex min-w-0 flex-col gap-2">
                <h3 id="ceo-health-inline" className="m-0 mt-eyebrow">Business at a glance</h3>
                <HealthStrip health={hub.health} onRefresh={() => void hub.refreshHealth()} />
              </section>
              <RecentDecisions status={hub.list.status} items={hub.list.items} onOpen={(id) => { hub.select(id); setView("chat"); }} />
            </div></div>}
            {activity}
          </div>
          </div>
        </section>

      </div>

      {/* CHAT BAR: always at the bottom, whichever view is open. */}
      <div className="sticky bottom-0 z-20 flex min-w-0 flex-shrink-0 flex-col gap-2 pb-1 pt-2" style={{ background: "linear-gradient(to top, var(--bg-base) 75%, transparent)" }} data-testid="chat-bar">
        <div className="ceo-read ceo-bar mx-auto flex w-full max-w-[820px] min-w-0 flex-col gap-2">
          {form && (
            <DecidePanel client={client} kind={form} disabled={processing} onClose={() => setForm(null)} onRun={(label, action) => { void send(label, null, action); setForm(null); }} />
          )}

          {!empty && (
            <div className="flex flex-shrink-0 flex-nowrap gap-1.5 overflow-x-auto pb-0.5" role="group" aria-label="Quick actions" data-testid="quick-row">
              {quick.map((q) => {
                const st = quickActionState(q, data?.agents ?? null, null);
                return (
                  <button key={q.id} type="button" disabled={!st.enabled || processing || closed} title={st.reason ?? undefined} onClick={() => void send(q.label, null, q.action)}
                    className="mt-chip mt-focus min-h-[36px] flex-shrink-0 whitespace-nowrap rounded-full px-3 py-1 t-meta sm:min-h-[32px]" style={{ color: "var(--text-3)", border: "1px solid var(--border-subtle)", opacity: st.enabled ? 1 : 0.45 }}>
                    {q.label}
                  </button>
                );
              })}
              <button type="button" disabled={processing || closed} onClick={() => void send("Should I stock a new product?", null, { kind: "PLAYBOOK", key: "NEW_PRODUCT_DECISION" })}
                className="mt-chip mt-focus min-h-[36px] flex-shrink-0 whitespace-nowrap rounded-full px-3 py-1 t-meta sm:min-h-[32px]" style={{ color: "var(--text-3)", border: "1px solid var(--border-subtle)" }}>
                New product decision
              </button>
            </div>
          )}

          <div className="hidden flex-shrink-0 items-center justify-between gap-2 px-1 t-meta sm:flex" style={{ color: "var(--text-5)" }} data-testid="connected-row">
            <span className="flex items-center gap-2">
              <span className="mt-eyebrow">Active specialists</span>
              {connected.map((n) => (
                <span key={n.code} title={n.name} className="flex h-6 w-6 items-center justify-center rounded-full font-bold" style={{ background: "var(--fill-hover)", color: "var(--text-2)", fontSize: 10 }}>{n.code}</span>
              ))}
            </span>
            <span>{hub.availability ? `${connected.length}/${nodes.length} connected` : "Checking specialist availability…"}</span>
          </div>

          <Composer
            disabled={processing || closed}
            placeholder={closed ? "This conversation is closed. Reopen it to continue." : needsInput ? "Answer here, or pick an option…" : "Ask the CEO agent anything…"}
            onSend={(t, files) => send(t, null, null, null, files)} fileStatus={(f) => fileStates[fileKey(f)]} fileInfo={(f) => fileInfos[fileKey(f)]}
            error={uploadError} initialText={initialDraft ?? undefined}
          />
        </div>
      </div>

      {drawer && (
        <div ref={drawerRef} tabIndex={-1} className="fixed inset-0 z-40 flex outline-none" role="dialog" aria-modal="true" aria-label="Conversations and business overview" data-testid="drawer">
          <button type="button" aria-label="Close panel" className="flex-1" style={{ background: "var(--ov-scrim, rgba(0,0,0,0.45))" }} onClick={() => setDrawer(false)} />
          <div className="flex w-[min(420px,92vw)] flex-col gap-5 overflow-y-auto p-4" style={{ background: "var(--bg-base)", borderLeft: "1px solid var(--border-subtle)" }}>
            <div className="flex items-center justify-between">
              <h2 className="m-0 t-card-title font-bold" style={{ color: "var(--text-1)" }}>Conversations</h2>
              <button type="button" aria-label="Close" onClick={() => setDrawer(false)} className="mt-btn mt-focus rounded-lg p-1.5" style={{ color: "var(--text-3)" }}><Icon name="close" size={16} /></button>
            </div>
            <InvestigationList
              status={hub.list.status} items={hub.list.items} error={hub.list.error} selectedId={hub.selectedId} showArchived={hub.showArchived}
              onToggleArchived={hub.setShowArchived} onDelete={(id) => void hub.removeConversation(id)} onSelect={(id) => { hub.select(id); setDrawer(false); }} onCreate={(t) => { void hub.create(t); setDrawer(false); }} onRetry={hub.refreshList}
            />
          </div>
        </div>
      )}
    </div>
  );
}
