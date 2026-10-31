"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/ui/EmptyState";
import { DecisionCard } from "@/components/ceo/hub/DecisionCard";
import { PickCard } from "@/components/ceo/hub/PickCard";
import { ListingPreviewCard } from "@/components/ceo/hub/ListingPreviewCard";
import { ReadinessCard } from "@/components/ceo/hub/ReadinessCard";
import { ListingCard } from "@/components/ceo/hub/ListingCard";
import { ListingHistoryCard } from "@/components/ceo/hub/ListingHistoryCard";
import { PerformanceCard } from "@/components/ceo/hub/PerformanceCard";
import { ImageQualityCard } from "@/components/ceo/hub/ImageQualityCard";
import { MarketIntelligenceCard } from "@/components/ceo/hub/MarketIntelligenceCard";
import { isMarketCard } from "@/lib/cmoMarket";
import { isImageCard, type ImagesApi } from "@/lib/cmoImages";
import { isPerformanceCard, type PerformanceApi } from "@/lib/cmoPerformance";
import { PlanCard } from "@/components/ceo/hub/PlanCard";
import { RichText } from "@/components/ceo/hub/RichText";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { isHistoryCard, isListingCard, isPickCard, isPreviewCard, isReadinessCard } from "@/lib/ceo";
import type { HistoryApi } from "@/lib/ceo";
import type { AgentCode, CeoMessage, ClarificationReply, ExplicitPeriod, FindingRow, InvestigationDetail, NeedRow, PlanView, TurnRow, UiAction } from "@/lib/ceo";
import { findingLink, investigationTitle, messageView, needStepView, needsByMessage, type HubState } from "@/lib/ceoModel";
import type { TurnProgress } from "@/lib/useCeoHub";

/** CENTER: the CEO conversation, the investigation's status and the composer.
 *
 * Everything shown as the CEO's words is the backend's stored, safety-gated message. The date range is an explicit control: when set,
 * it is sent with the question and the backend uses it as THE period: the model never chooses it. The "ideas" chips only fill the
 * composer; they send nothing. The quick actions DO send: each asks for one catalog item directly, so no model has to work out what you
 * meant (faster, and no misreading). The backend still applies every attachment, permission and plan check. */
export function Conversation({
  onOpenForm,
  state,
  detail,
  turn,
  needs = [],
  notice,
  onDismissNotice,
  onSend,
  onResolve,
  onReopen,
  onArchive,
  onRetry,
  awaiting = false,
  onApprovePlan,
  onDeclinePlan,
  planBusy = null,
  loadAttachmentImage,
  approveListing,
  historyApi,
  performanceApi,
  imagesApi,
  recordListingCopy,
}: {
  /** loads the seller's own picture for the listing preview (authenticated, images only); absent = the preview shows its neutral placeholder */
  loadAttachmentImage?: (investigationId: string, attachmentId: string) => Promise<string>;
  approveListing?: (generationId: string) => Promise<{ approved: boolean; message: string; banner: string | null }>;
  historyApi?: HistoryApi;
  performanceApi?: PerformanceApi;
  imagesApi?: ImagesApi;
  recordListingCopy?: (generationId: string) => Promise<boolean>;
  /** the Approve / Decline buttons of a plan card (the only approval there is); absent = the cards are read-only */
  onApprovePlan?: (planId: string, planHash: string) => void;
  onDeclinePlan?: (planId: string) => void;
  planBusy?: string | null;
  /** the stored thread ends with a question that has no answer yet (page reopened mid-run, or the reply was lost) */
  awaiting?: boolean;
  onOpenForm: (form: string) => void;
  state: HubState;
  detail: InvestigationDetail | null;
  turn: TurnProgress;
  /** the CEO's follow-up lookups for this investigation (read from the backend) */
  needs?: NeedRow[];
  notice: string | null;
  onDismissNotice: () => void;
  onSend: (message: string, period: ExplicitPeriod | null, action?: UiAction | null, clarification?: ClarificationReply | null) => void;
  onResolve: (note: string) => void;
  onReopen: () => void;
  onArchive: () => void;
  onRetry: () => void;
}) {
  if (state === "NO_SELECTION") {
    return (
      <EmptyState
        icon="ceo"
        title="Select or start a conversation"
        description="Open one from Conversations, or just type below to start a new one. The CEO answers from your saved results and the specialists you wire in, and says plainly what it could not check."
      />
    );
  }
  if (state === "LOADING") return <LoadingState lines={6} label="Loading investigation" />;
  if (state === "NOT_FOUND") return <EmptyState icon="lock" title="Investigation not found" description="It does not exist, or it is not part of your business." />;
  if (state === "ERROR" || !detail) return <ErrorNotice message="Could not load this investigation." onRetry={onRetry} />;

  const inv = detail.investigation;
  const closed = state === "RESOLVED" || state === "ARCHIVED";
  const turnById = new Map(detail.turns.map((t) => [t.id, t]));

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-6" data-testid="conversation" data-state={state}>
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <h2 className="m-0 truncate t-card-title font-semibold" title={investigationTitle(inv)} style={{ color: "var(--text-1)" }}>
            {investigationTitle(inv)}
          </h2>
        </div>
        <StatusControls status={inv.status} processing={state === "PROCESSING"} onResolve={onResolve} onReopen={onReopen} onArchive={onArchive} />
      </header>

      {state === "RESOLVED" && (
        <Banner tone="info" title="Resolved">
          {inv.resolution_note ? <>Your note: {inv.resolution_note}</> : "This investigation was marked resolved."} It stays here as business history; new questions are closed until you reopen it.
        </Banner>
      )}
      {state === "ARCHIVED" && (
        <Banner tone="neutral" title="Archived">
          Hidden from your list by default and closed to new questions. Everything in it is still readable.
        </Banner>
      )}
      {notice && <ErrorNotice message={notice} onRetry={onDismissNotice} />}

      <Thread
        messages={detail.messages}
        findings={detail.findings}
        turnById={turnById}
        answerableCardId={closed ? null : lastCardId(detail.messages)}
        cardDisabled={state === "PROCESSING"}
        onAnswer={(reply, text) => onSend(text, null, null, reply)}
        onOpenForm={onOpenForm}
        onSuggest={(label, action) => onSend(label, null, action)}
        onAsk={(text) => onSend(text, null)}
        agents={detail.agents}
        needs={needs}
        plans={detail.plans ?? []}
        closed={closed}
        planBusy={planBusy}
        onApprovePlan={onApprovePlan}
        onDeclinePlan={onDeclinePlan}
        loadImage={loadAttachmentImage}
        onApproveListing={approveListing}
        historyApi={historyApi}
        performanceApi={performanceApi}
        imagesApi={imagesApi}
        onListingCopied={(id) => void recordListingCopy?.(id)}
      />


      {state === "PROCESSING" && <Processing question={turn.question} arrived={turn.arrivedIds.length} stage={turn.stage} />}
      {awaiting && state !== "PROCESSING" && !closed && (
        <div role="status" aria-live="polite" data-testid="awaiting-answer" className="flex items-center gap-3 rounded-xl px-3.5 py-3 t-body-sm" style={{ border: "1px dashed var(--accent-border-default)", color: "var(--text-3)" }}>
          <Spinner />
          <span className="min-w-0 flex-1">
            Your last question has no answer yet. It may still be running, and this page checks again every few seconds. It has not been reported as done. If it never arrives, send your next message: an interrupted request is settled and reported honestly.
          </span>
        </div>
      )}
      {turn.error && state !== "PROCESSING" && <ErrorNotice message={turn.error} />}

    </div>
  );
}

function Banner({ tone, title, children }: { tone: "info" | "neutral"; title: string; children: React.ReactNode }) {
  return (
    <div role="status" className="flex flex-wrap items-start gap-2.5 rounded-xl px-3.5 py-2.5 t-body-sm" style={{ background: "var(--fill-hover)", color: "var(--text-3)" }}>
      <StatusBadge tone={tone}>{title}</StatusBadge>
      <span className="min-w-0 flex-1">{children}</span>
    </div>
  );
}

function Processing({ question, arrived, stage }: { question: string | null; arrived: number; stage: string | null }) {
  // The checklist is the live event stream's own stage words, in the order they arrived (nothing is invented: no events, no list). The latest is still running.
  const [seen, setSeen] = useState<string[]>([]);
  if (stage && seen[seen.length - 1] !== stage) setSeen([...seen, stage]);
  return (
    <div role="status" aria-live="polite" data-testid="processing" className="mt-hub-card flex flex-col gap-2.5 px-3.5 py-3 t-body-sm" style={{ borderStyle: "dashed", borderColor: "var(--accent-border-default)", color: "var(--text-3)" }}>
      <div className="flex items-center gap-3">
        <Spinner />
        <span className="min-w-0 flex-1">
          The CEO is working on {question ? <>&ldquo;{question}&rdquo;</> : "your question"}.{stage ? <span data-testid="stage"> {stage}</span> : null}{" "}
          {arrived > 0 ? `${arrived} ${arrived === 1 ? "finding has" : "findings have"} arrived so far; see the activity panel.` : "Findings appear in the activity panel as each specialist finishes."}
        </span>
      </div>
      {seen.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Progress" data-testid="progress-steps">
          {seen.map((step, i) => {
            const running = i === seen.length - 1;
            return (
              <li key={`${i}-${step}`} data-state={running ? "running" : "done"} className="flex items-center gap-2 t-meta" style={{ color: "var(--text-3)" }}>
                {running ? <Spinner size={14} /> : <span aria-hidden style={{ color: "var(--accent)" }}><Icon name="check" size={15} strokeWidth={1.8} /></span>}
                <span>{step}</span>
                <span className="sr-only">{running ? " (in progress)" : " (done)"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** A decision card can be answered only while it is the latest message: once anything follows it, it has been answered or overtaken. */
function lastCardId(messages: CeoMessage[]): string | null {
  const last = messages[messages.length - 1];
  return last && last.role === "CEO" && last.kind === "CLARIFICATION" && last.choices ? last.id : null;
}

function Thread({
  messages, findings, turnById, answerableCardId, cardDisabled, onAnswer, onOpenForm, onSuggest, onAsk, agents, needs, plans, closed, planBusy, onApprovePlan, onDeclinePlan, loadImage, onApproveListing, historyApi, performanceApi, imagesApi, onListingCopied,
}: {
  loadImage?: (investigationId: string, attachmentId: string) => Promise<string>;
  onApproveListing?: (generationId: string) => Promise<{ approved: boolean; message: string; banner: string | null }>;
  historyApi?: HistoryApi;
  performanceApi?: PerformanceApi;
  imagesApi?: ImagesApi;
  onListingCopied?: (generationId: string) => void;
  plans: PlanView[];
  closed: boolean;
  planBusy: string | null;
  onApprovePlan?: (planId: string, planHash: string) => void;
  onDeclinePlan?: (planId: string) => void;
  messages: CeoMessage[];
  findings: FindingRow[];
  turnById: Map<string, TurnRow>;
  answerableCardId: string | null;
  cardDisabled: boolean;
  onAnswer: (reply: ClarificationReply, text: string) => void;
  onOpenForm: (form: string) => void;
  onSuggest: (label: string, action: UiAction) => void;
  onAsk: (text: string) => void;
  agents: Partial<Record<AgentCode, boolean>> | null;
  needs: NeedRow[];
}) {
  const placed = needsByMessage(needs, messages);
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);
  if (messages.length === 0) return <Welcome agents={agents} onAsk={onAsk} onAction={onSuggest} onOpenForm={onOpenForm} />;
  return (
    <ol tabIndex={0} className="mt-focus m-0 flex min-h-0 flex-1 list-none flex-col gap-7 overflow-y-auto rounded-lg p-0 pr-1" aria-label="Conversation" aria-live="polite">
      {messages.map((m) => (
        <li key={m.id}>
          <Bubble message={m} turnById={turnById} findings={findings} />
          {m.role === "CEO" && m.kind === "PLAN" && (
            <PlanCard plan={plans.find((p) => p.plannedTurnId === m.turn_id) ?? null} busy={planBusy} closed={closed} onApprove={onApprovePlan} onDecline={onDeclinePlan} />
          )}
          {m.role === "CEO" && m.kind === "ANSWER" && <ReportButtons links={reportLinks(findings, m.turn_id)} />}
          <NeedSteps needs={placed.byMessage.get(m.id) ?? []} />
          {m.role === "CEO" && (m.kind === "ANSWER" || m.kind === "CLARIFICATION") && isPickCard(m.choices) && m.id === messages[messages.length - 1]?.id && (
            <PickCard card={m.choices} disabled={cardDisabled} onSend={onAsk} />
          )}
          {m.role === "CEO" && m.kind === "ANSWER" && isPreviewCard(m.choices) && <ListingPreviewCard card={m.choices} loadImage={loadImage} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isReadinessCard(m.choices) && <ReadinessCard card={m.choices} disabled={cardDisabled} onSend={onAsk} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isListingCard(m.choices) && <ListingCard card={m.choices} disabled={cardDisabled} onSend={onAsk} onApprove={onApproveListing} onCopied={onListingCopied} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isHistoryCard(m.choices) && <ListingHistoryCard card={m.choices} api={historyApi} disabled={cardDisabled} onSend={onAsk} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isPerformanceCard(m.choices) && <PerformanceCard card={m.choices} api={performanceApi} disabled={cardDisabled} onSend={onAsk} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isMarketCard(m.choices) && <MarketIntelligenceCard card={m.choices} disabled={cardDisabled} onSend={onAsk} />}
          {m.role === "CEO" && m.kind === "ANSWER" && isImageCard(m.choices) && <ImageQualityCard card={m.choices} api={imagesApi} disabled={cardDisabled} onSend={onAsk} />}
          {m.id === answerableCardId && m.choices && !isPickCard(m.choices) && !isPreviewCard(m.choices) && !isReadinessCard(m.choices) && !isListingCard(m.choices) && !isHistoryCard(m.choices) && !isPerformanceCard(m.choices) && !isImageCard(m.choices) && !isMarketCard(m.choices) && <DecisionCard messageId={m.id} question={m.content} card={m.choices} disabled={cardDisabled} onAnswer={onAnswer} onOpenForm={onOpenForm} />}
        </li>
      ))}
      {placed.unplaced.length > 0 && <li><NeedSteps needs={placed.unplaced} /></li>}
      <li ref={end} aria-hidden="true" className="h-0 overflow-hidden" />
    </ol>
  );
}

/** The CEO's follow-up lookups made for a specialist, one plain line each: who asked whom for what, and how it ended. Text is fixed labels plus the
 * backend's status; the specialist's own result is a separate finding and is never merged into this line. */
function NeedSteps({ needs }: { needs: NeedRow[] }) {
  if (needs.length === 0) return null;
  return (
    <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0" aria-label="Follow-up lookups" data-testid="need-steps">
      {needs.map((n) => {
        const v = needStepView(n);
        return (
          <li key={n.id} data-testid={`need-step-${n.id}`} data-status={n.status} className="flex flex-wrap items-center gap-x-2 t-meta" style={{ color: "var(--text-5)" }}>
            <span>{v.text}</span>
            <StatusBadge tone={v.tone === "positive" ? "accent" : v.tone === "warning" ? "warning" : "neutral"}>{v.outcome}</StatusBadge>
          </li>
        );
      })}
    </ul>
  );
}

/** One button per agent page that holds the full analysis behind this answer (for example the whole research report with images, reviews and suppliers). */
function reportLinks(findings: FindingRow[], turnId: string | null | undefined): { href: string; label: string }[] {
  if (!turnId) return [];
  const out: { href: string; label: string }[] = [];
  for (const f of findings) {
    const l = f.turn_id === turnId ? findingLink(f) : null;
    if (l && !out.some((o) => o.href === l.href)) out.push(l);
  }
  return out;
}

function ReportButtons({ links }: { links: { href: string; label: string }[] }) {
  if (links.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-2" data-testid="report-buttons">
      {links.map((l) => (
        <Link key={l.href} href={l.href} data-testid="report-button" className="mt-btn mt-focus inline-flex min-h-[40px] items-center gap-1.5 rounded-lg px-3 py-1.5 t-body-sm font-bold sm:min-h-0" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
          {l.label} &rarr;
        </Link>
      ))}
    </div>
  );
}

const timeOf = (iso: string): string => {
  const d = new Date(iso);
  return d.toString() === "Invalid Date" ? "" : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
};

/** "Key Insights": only when this answer's own saved results carry structured facts or figures (the backend's snapshot, verbatim, never re-worded or computed here). */
function insightsFor(findings: FindingRow[], turnId: string | null | undefined): { key: string; text: string; register?: string }[] {
  if (!turnId) return [];
  const out: { key: string; text: string; register?: string }[] = [];
  for (const f of findings) {
    if (f.turn_id !== turnId || f.status !== "COMPLETE" || !f.presentation) continue;
    f.presentation.facts.forEach((x, i) => out.push({ key: `${f.id}-fact-${i}`, text: `${x.label}: ${x.text}` }));
    f.presentation.figures.forEach((x) => out.push({ key: `${f.id}-fig-${x.ref.kind}-${x.ref.id}-${x.label}`, text: `${x.label}: ${x.value}`, register: x.register }));
  }
  return out.slice(0, 5);
}

function KeyInsights({ items }: { items: { key: string; text: string; register?: string }[] }) {
  if (items.length === 0) return null;
  return (
    <section aria-label="Key insights" data-testid="key-insights" className="mt-3 rounded-xl px-3.5 py-3" style={{ background: "var(--accent-fill-subtle)", border: "1px solid var(--accent-border-subtle)" }}>
      <h4 className="m-0 mb-1.5 flex items-center gap-1.5 t-meta font-semibold" style={{ color: "var(--accent)" }}>
        <Icon name="reports" size={14} /> Key Insights
      </h4>
      <ul className="m-0 flex list-disc flex-col gap-1 pl-4">
        {items.map((it) => (
          <li key={it.key} className="t-body-sm" style={{ color: "var(--text-2)" }}>
            {it.text} {it.register && <ProvenanceBadge register={it.register} />}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Bubble({ message, turnById, findings }: { message: CeoMessage; turnById: Map<string, TurnRow>; findings: FindingRow[] }) {
  const v = messageView(message, turnById);
  if (v.tone === "note") {
    return (
      <div className="text-center t-meta" style={{ color: "var(--text-6)" }} data-testid="system-note">
        {message.content}
      </div>
    );
  }
  const mine = v.tone === "user";
  const insights = !mine && message.kind === "ANSWER" ? insightsFor(findings, message.turn_id) : [];
  const state = message.pending ? "Sending…" : message.failed ? "Not sent" : null;
  return (
    <div data-testid={mine ? "message-user" : "message-ceo"} className={`ceo-msg flex flex-col gap-2 ${mine ? "items-end" : "items-start"}`} style={{ opacity: message.pending ? 0.7 : 1 }}>
      <span className="sr-only">{mine ? "You" : "CEO Agent"}</span>
      {/* the seller's words sit in a soft pill on the right; the CEO's answer is plain text on the page, with no box, as in a chat app */}
      <div
        className={mine ? "ceo-msg-user min-w-0 max-w-[78%] rounded-3xl px-4 py-2.5" : `min-w-0 w-full ${v.tone === "clarify" ? "border-l-2 pl-3" : ""}`}
        style={v.tone === "clarify" ? { borderColor: "var(--warning)" } : undefined}
      >
        {v.badge && <div className="mb-1"><StatusBadge tone={v.tone === "clarify" ? "warning" : "neutral"}>{v.badge}</StatusBadge></div>}
        {/* the backend's gated text, shown verbatim: line breaks kept, nothing re-formatted or re-computed here */}
        <div className={`${mine ? "whitespace-pre-wrap " : ""}break-words t-body`} style={{ color: "var(--text-1)", lineHeight: 1.7 }}>
          {mine ? message.content : <RichText text={message.content} />}
        </div>
        {v.footnote && (
          <div className="mt-2 t-meta" style={{ color: "var(--text-6)" }}>
            {v.footnote}
          </div>
        )}
        <KeyInsights items={insights} />
      </div>
      <div className={`flex items-center gap-2 t-meta ${mine ? "pr-1" : ""}`} style={{ color: "var(--text-6)" }}>
        {state ? <span>{state}</span> : <time dateTime={message.created_at}>{timeOf(message.created_at)}</time>}
        {!mine && !state && <CopyButton text={message.content} />}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" aria-label={done ? "Copied" : "Copy answer"} title={done ? "Copied" : "Copy answer"} className="ceo-icon mt-focus" style={{ width: 28, height: 28 }}
      onClick={() => { void navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }}>
      <Icon name={done ? "check" : "copy"} size={15} />
    </button>
  );
}

function StatusControls({ status, processing, onResolve, onReopen, onArchive }: { status: string; processing: boolean; onResolve: (note: string) => void; onReopen: () => void; onArchive: () => void }) {
  const [mode, setMode] = useState<"none" | "resolve" | "archive">("none");
  const [note, setNote] = useState("");
  if (status === "ARCHIVED") return <StatusBadge tone="neutral">Archived</StatusBadge>;
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        {status === "ACTIVE" ? <StatusBadge tone="accent" dot>Active</StatusBadge> : <StatusBadge tone="info">Resolved</StatusBadge>}
        {status === "ACTIVE" && (
          <button type="button" disabled={processing} onClick={() => setMode(mode === "resolve" ? "none" : "resolve")} className="mt-btn mt-focus min-h-[36px] rounded-lg px-3 py-1 t-meta font-bold sm:min-h-0 sm:px-2.5" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Resolve
          </button>
        )}
        {status === "RESOLVED" && (
          <button type="button" onClick={onReopen} className="mt-btn mt-focus min-h-[36px] rounded-lg px-3 py-1 t-meta font-bold sm:min-h-0 sm:px-2.5" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Reopen
          </button>
        )}
        <button type="button" disabled={processing} onClick={() => setMode(mode === "archive" ? "none" : "archive")} className="mt-btn mt-focus min-h-[36px] rounded-lg px-3 py-1 t-meta font-bold sm:min-h-0 sm:px-2.5" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
          Archive
        </button>
      </div>
      {mode === "resolve" && (
        <form
          className="flex w-[min(360px,80vw)] flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!note.trim()) return;
            onResolve(note.trim());
            setNote("");
            setMode("none");
          }}
        >
          <label className="t-meta" htmlFor="resolve-note" style={{ color: "var(--text-5)" }}>
            What did you conclude? (your own note, required)
          </label>
          <textarea id="resolve-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000} className="mt-focus rounded-lg bg-transparent p-2 t-body-sm outline-none" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }} />
          <button type="submit" disabled={!note.trim()} className="mt-btn mt-focus self-end rounded-lg px-3 py-1.5 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: note.trim() ? 1 : 0.5 }}>
            Mark resolved
          </button>
        </form>
      )}
      {mode === "archive" && (
        <div className="flex items-center gap-2 t-body-sm" style={{ color: "var(--text-4)" }}>
          Hide this investigation?
          <button type="button" onClick={() => { onArchive(); setMode("none"); }} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
            Archive
          </button>
        </div>
      )}
    </div>
  );
}
