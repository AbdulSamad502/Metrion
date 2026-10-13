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
import { InvestigationList } from "@/components/ceo/hub/InvestigationList";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { MemoryPanel } from "@/components/ceo/hub/MemoryPanel";
import { SharedFindingsPanel } from "@/components/ceo/hub/SharedFindingsPanel";
import { RecentDecisions } from "@/components/ceo/hub/RecentDecisions";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError } from "@/lib/api";
import { createCeoClient, type AgentCode, type CeoClient, type UiAction } from "@/lib/ceo";
import { canvasNodes, QUICK_ACTIONS, quickActionState } from "@/lib/ceoModel";
import type { FeedFactory } from "@/lib/ceoPolling";
import { useCeoHub } from "@/lib/useCeoHub";
import { useDesktopLayout, useWideLayout } from "@/lib/useDesktopLayout";
import { useModalFocus } from "@/lib/useModalFocus";

/** The real CEO Hub. Production wiring: the typed client over the signed-in user's Clerk token. */
export function CeoHub() {
  const { getToken } = useAuth();
  const client = useMemo(() => createCeoClient(getToken), [getToken]);
  // A link from another page can open a decision form directly (e.g. Products → /dashboard/ceo-hub?form=new-product); anything else is ignored.
  const initialForm = FORM_LINKS[useSearchParams().get("form") ?? ""] ?? null;
  return <CeoHubWorkspace client={client} initialForm={initialForm} />;
}

const FORM_LINKS: Record<string, DecideKind> = { "new-product": "NEW_PRODUCT_DECISION", "price-impact": "COMPETITOR_PRICE_IMPACT" };

const agentOf = (action: string): AgentCode | null => ({ cfo: "CFO", ci: "CI", pi: "PI", cmo: "CMO" } as Record<string, AgentCode>)[action.split(".")[0]] ?? null;
const ACTION_WORDS: Record<string, string> = { pricing: "margin check", landed_cost: "landed cost", batch_size: "batch size", supplier_ranking: "supplier ranking", request_price_scenario: "price comparison", report: "report" };
const workLabel = (action: string) => `Working · ${ACTION_WORDS[action.split(".")[1] ?? ""] ?? (action.split(".")[1] ?? "").replace(/_/g, " ")}`;

/** One conversation, two columns (the reference layout). Left: the CEO and its agents on wires, what is running now (from the live event stream) and the
 * work behind the answers. Right, and wider: the conversation, with the chat bar fixed at the bottom of its own column. Below the desktop breakpoint the
 * two are tabs, so the conversation is never squeezed. The hub holds no orchestration logic: the backend classifies, validates, runs the specialists,
 * synthesises and safety-gates. */
export function CeoHubWorkspace({ client, feedFactory, pollMs, initialForm = null }: { client: CeoClient; feedFactory?: FeedFactory; pollMs?: number; initialForm?: DecideKind | null }) {
  const hub = useCeoHub(client, feedFactory, pollMs);
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
  /** Below the desktop breakpoint the conversation is full width and the task activity is one tap away; both stay mounted. */
  const [mobileView, setMobileView] = useState<"chat" | "activity">("chat");
  const desktop = useDesktopLayout();
  const wide = useWideLayout();
  /** Wide screens: the right column has two views, the conversation and the activity / results; both stay mounted. */
  const [rightView, setRightView] = useState<"chat" | "results">("chat");
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
    void hub.sendTurn(message || "Please read what I attached.", period, action, clarification, ids); // the turn reports its own progress and errors; the composer must not wait for the whole answer
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
  // On a phone the four tall specialist cards would push what is running and what was found a screen and a half down, so there the canvas follows the activity. The
  // document order changes with it (not CSS `order`), so the keyboard order always matches what is on screen.
  const canvas = (
    <AgentCanvas
      nodes={nodes} busy={hub.busyAgent} onToggle={(c, attach) => void toggleAgent(c, attach)}
      working={workingByAgent} ceoStatus={ceoStatus} ceoTone={ceoTone}
    />
  );
  const connected = nodes.filter((n) => n.state === "ATTACHED");
  const quick = QUICK_ACTIONS.filter((q) => ["pnl", "research", "competitors"].includes(q.id));
  const panelH = "h-[calc(100dvh-215px)] min-h-[440px] xl:h-[calc(100dvh-150px)]";
  const tabs = [["chat", "Conversation"], ["activity", processing ? "Activity · live" : needsInput ? "Activity · waiting" : "Activity"]] as const;

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

  return (
    <div className="flex flex-col gap-3" data-testid="ceo-hub">
      {/* The conversation list could never be loaded (nothing is shown from earlier): the backend is unreachable or refused. Said once, here, with a retry, instead of a screen that looks like a normal empty start. When an earlier list is on screen, the existing "could not refresh" notice covers it instead (no second message). */}
      {hub.list.status === "error" && hub.list.items.length === 0 && (
        <div data-testid="hub-unavailable"><ErrorNotice message={`Your conversations could not be loaded. ${hub.list.error ?? ""}`.trim()} onRetry={hub.refreshList} /></div>
      )}
      <div className="flex gap-1 xl:hidden" role="tablist" aria-label="Conversation or task activity">
        {tabs.map(([id, label]) => (
          <button
            key={id} type="button" role="tab" aria-selected={mobileView === id} data-testid={`mobile-tab-${id}`} onClick={() => setMobileView(id)}
            className="mt-btn mt-focus min-h-[44px] flex-1 rounded-lg px-3 py-2 t-body-sm font-semibold"
            style={{ border: "1px solid var(--border-subtle)", color: mobileView === id ? "var(--text-1)" : "var(--text-4)", background: mobileView === id ? "var(--fill-hover)" : "transparent" }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(480px,44%)]">
        {/* LEFT / "Activity" tab: who the CEO works with, what is running, and what the specialists found. */}
        <section
          className={`mt-panel min-w-0 flex-col gap-5 overflow-y-auto p-4 xl:flex ${panelH} ${mobileView === "activity" ? "flex" : "hidden"}`}
          aria-label="Specialists and task activity" data-testid="work-area"
        >
          <header className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h2 className="m-0 t-card-title font-bold" style={{ color: "var(--text-1)" }}>Your specialists</h2>
              <p className="m-0 mt-0.5 t-meta" style={{ color: "var(--text-5)" }}>
                {data ? `Investigation · ${new Date(data.investigation.created_at).toLocaleDateString()}` : "Metrion sends each question to the right specialist. Remove one to stop it being used here; a new conversation starts with all of them."}
              </p>
            </div>
            {data && <StatusBadge tone={data.investigation.status === "ACTIVE" ? "accent" : "neutral"} dot={data.investigation.status === "ACTIVE"}>{data.investigation.status === "ACTIVE" ? "Active" : data.investigation.status.toLowerCase()}</StatusBadge>}
          </header>

          {desktop && canvas}
          {(hub.health.entries.length > 0 || hub.health.status === "error" || hub.list.items.length > 0) && <div className="@container"><div className="grid grid-cols-1 gap-3 @[760px]:grid-cols-2" data-testid="summary-cards">
            <section aria-labelledby="ceo-health-inline" className="flex min-w-0 flex-col gap-2">
              <h3 id="ceo-health-inline" className="m-0 mt-eyebrow">Business at a glance</h3>
              <HealthStrip health={hub.health} onRefresh={() => void hub.refreshHealth()} />
            </section>
            <RecentDecisions status={hub.list.status} items={hub.list.items} onOpen={(id) => hub.select(id)} />
          </div></div>}

          {!desktop && canvas}
          {!wide && activity}
        </section>

        {/* RIGHT / "Conversation" tab: the dominant column. Messages scroll; the chat bar stays at the bottom. */}
        <section
          className={`mt-panel min-w-0 flex-col gap-3 p-4 xl:flex ${panelH} ${mobileView === "chat" ? "flex" : "hidden"}`}
          aria-label="CEO conversation" data-testid="chat-column"
        >
          <header className="flex items-center gap-3 pb-2" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl" style={{ background: "var(--fill-hover)", color: "var(--accent)" }}><Icon name="ceo" size={18} /></span>
            <div className="min-w-0 flex-1">
              <div className="t-body font-bold" style={{ color: "var(--text-1)" }}>CEO</div>
              <div className="truncate t-meta" style={{ color: needsInput ? "var(--warning)" : "var(--text-5)" }} data-testid="chat-status">{ceoStatus}</div>
            </div>
            <button type="button" onClick={() => setDrawer(true)} aria-label="Conversations and business overview" data-testid="open-drawer" className="mt-btn mt-focus flex min-h-[40px] items-center gap-1.5 rounded-lg px-2.5 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)" }}>
              <Icon name="menu" size={14} /> Conversations
            </button>
          </header>

          {wide && (
            <div className="flex gap-1" role="tablist" aria-label="Conversation or activity and results">
              {([["chat", "Conversation"], ["results", processing ? "Activity & results · live" : needsInput ? "Activity & results · waiting" : "Activity & results"]] as const).map(([id, label]) => (
                <button key={id} type="button" role="tab" aria-selected={rightView === id} data-testid={`right-tab-${id}`} onClick={() => setRightView(id)}
                  className="mt-btn mt-focus min-h-[36px] flex-1 rounded-lg px-3 py-1.5 t-body-sm font-semibold"
                  style={{ border: "1px solid var(--border-subtle)", color: rightView === id ? "var(--text-1)" : "var(--text-4)", background: rightView === id ? "var(--fill-hover)" : "transparent" }}>
                  {label}
                </button>
              ))}
            </div>
          )}
          {wide && (
            <div className={`min-h-0 flex-1 flex-col gap-5 overflow-y-auto ${rightView === "results" ? "flex" : "hidden"}`} data-testid="results-area" role="tabpanel" aria-label="Activity and results">
              {activity}
            </div>
          )}

          <div className={`min-h-0 flex-1 flex-col gap-3 ${wide && rightView === "results" ? "hidden" : "flex"}`}>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {empty ? (
              <Welcome agents={{ CI: true, CFO: true, PI: true, CMO: true }} onAsk={(t) => void send(t, null)} onAction={(l, a) => void send(l, null, a)} onOpenForm={(f) => setForm(f as DecideKind)} />
            ) : (
              <Conversation
                onOpenForm={(f) => setForm(f as DecideKind)} state={hub.state} detail={data} turn={hub.turn} needs={hub.needs} notice={hub.notice} onDismissNotice={hub.dismissNotice}
                onSend={hub.sendTurn} awaiting={hub.awaitingAnswer} onApprovePlan={(id, h) => void hub.approvePlan(id, h)} onDeclinePlan={(id) => void hub.declinePlan(id)} planBusy={hub.planBusy} onResolve={hub.resolve} onReopen={hub.reopen} onArchive={hub.archive} onRetry={() => void hub.retryDetail()}
              />
            )}
          </div>

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
            placeholder={closed ? "This conversation is closed. Reopen it to continue." : needsInput ? "Answer here, or pick an option…" : "Ask the CEO anything…"}
            onSend={(t, files) => send(t, null, null, null, files)} fileStatus={(f) => fileStates[fileKey(f)]} fileInfo={(f) => fileInfos[fileKey(f)]}
            error={uploadError}
          />
          </div>
        </section>
      </div>

      {drawer && (
        <div ref={drawerRef} tabIndex={-1} className="fixed inset-0 z-40 flex outline-none" role="dialog" aria-modal="true" aria-label="Conversations and business overview" data-testid="drawer">
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
