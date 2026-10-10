"use client";

import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { Welcome } from "@/components/ceo/hub/Welcome";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { AgentCode, CeoMessage, ClarificationCard, ClarificationReply, ExplicitPeriod, InvestigationDetail, NeedRow, TurnRow, UiAction } from "@/lib/ceo";
import { investigationTitle, messageView, needStepView, needsByMessage, type HubState } from "@/lib/ceoModel";
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
}: {
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
        title="Select or start an investigation"
        description="Pick one on the left, or start a new one. The CEO answers from your saved results and the specialists you wire in, and says plainly what it could not check."
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
    <div className="flex h-full min-h-0 flex-col gap-3" data-testid="conversation" data-state={state}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="mt-eyebrow">Conversation</h2>
          <div className="mt-1 t-card-title font-semibold" style={{ color: "var(--text-1)" }}>
            {investigationTitle(inv)}
          </div>
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
        turnById={turnById}
        answerableCardId={closed ? null : lastCardId(detail.messages)}
        cardDisabled={state === "PROCESSING"}
        onAnswer={(reply, text) => onSend(text, null, null, reply)}
        onOpenForm={onOpenForm}
        onSuggest={(label, action) => onSend(label, null, action)}
        onAsk={(text) => onSend(text, null)}
        agents={detail.agents}
        needs={needs}
      />


      {state === "PROCESSING" && <Processing question={turn.question} arrived={turn.arrivedIds.length} stage={turn.stage} />}
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
  return (
    <div role="status" aria-live="polite" data-testid="processing" className="flex items-center gap-3 rounded-xl px-3.5 py-3 t-body-sm" style={{ border: "1px dashed var(--accent-border-default)", color: "var(--text-3)" }}>
      <Spinner />
      <span className="min-w-0 flex-1">
        The CEO is working on {question ? <>&ldquo;{question}&rdquo;</> : "your question"}.{stage ? <span data-testid="stage"> {stage}</span> : null}{" "}
        {arrived > 0 ? `${arrived} ${arrived === 1 ? "finding has" : "findings have"} arrived so far; see the panel on the right.` : "Findings appear on the right as each specialist finishes."}
      </span>
    </div>
  );
}

/** A decision card can be answered only while it is the latest message: once anything follows it, it has been answered or overtaken. */
function lastCardId(messages: CeoMessage[]): string | null {
  const last = messages[messages.length - 1];
  return last && last.role === "CEO" && last.kind === "CLARIFICATION" && last.choices ? last.id : null;
}

function Thread({
  messages, turnById, answerableCardId, cardDisabled, onAnswer, onOpenForm, onSuggest, onAsk, agents, needs,
}: {
  messages: CeoMessage[];
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
  const end = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);
  if (messages.length === 0) return <Welcome agents={agents} onAsk={onAsk} onAction={onSuggest} onOpenForm={onOpenForm} />;
  return (
    <ol className="m-0 flex min-h-0 flex-1 list-none flex-col gap-3 overflow-y-auto p-0 pr-1" aria-label="Conversation" aria-live="polite">
      {messages.map((m) => (
        <li key={m.id}>
          <Bubble message={m} turnById={turnById} />
          <NeedSteps needs={placed.byMessage.get(m.id) ?? []} />
          {m.id === answerableCardId && m.choices && <DecisionCard messageId={m.id} card={m.choices} disabled={cardDisabled} onAnswer={onAnswer} onOpenForm={onOpenForm} />}
        </li>
      ))}
      {placed.unplaced.length > 0 && <li><NeedSteps needs={placed.unplaced} /></li>}
      <div ref={end} />
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

function Bubble({ message, turnById }: { message: CeoMessage; turnById: Map<string, TurnRow> }) {
  const v = messageView(message, turnById);
  if (v.tone === "note") {
    return (
      <div className="text-center t-meta" style={{ color: "var(--text-6)" }} data-testid="system-note">
        {message.content}
      </div>
    );
  }
  const mine = v.tone === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        data-testid={mine ? "message-user" : "message-ceo"}
        className="max-w-[88%] rounded-2xl px-4 py-3"
        style={{
          background: mine ? "var(--fill-hover)" : "var(--bg-card)",
          border: `1px solid ${v.tone === "clarify" ? "var(--warning-border)" : "var(--border-subtle)"}`,
          opacity: message.pending ? 0.7 : 1,
        }}
      >
        {v.badge && (
          <div className="mb-1.5">
            <StatusBadge tone={v.tone === "clarify" ? "warning" : "neutral"}>{v.badge}</StatusBadge>
          </div>
        )}
        {/* the backend's gated text, shown verbatim: line breaks kept, nothing re-formatted or re-computed here */}
        <div className="whitespace-pre-wrap t-body" style={{ color: "var(--text-2)" }}>
          {message.content}
        </div>
        {v.footnote && (
          <div className="mt-2 t-meta" style={{ color: "var(--text-6)" }}>
            {v.footnote}
          </div>
        )}
      </div>
    </div>
  );
}

/** The backend's decision card (spec 6.32): real options built from the seller's own data, the recommended one first with the rule that recommends it, then
 * "Other". Choosing sends the option's key; the backend resumes the pending question with no model call and the same checks. Nothing is chosen for the seller. */
function DecisionCard({ messageId, card, disabled, onAnswer, onOpenForm }: { messageId: string; card: ClarificationCard; disabled: boolean; onAnswer: (reply: ClarificationReply, text: string) => void; onOpenForm: (form: string) => void }) {
  const [typing, setTyping] = useState(false);
  const [other, setOther] = useState("");
  const input = card.kind === "INPUT"; // a question the CEO is asking: the answer is typed in the chat bar (or chosen here)
  const real = card.options.filter((o) => o.kind !== "OTHER" && o.kind !== "CANCEL");
  const cancel = card.options.find((o) => o.kind === "CANCEL");
  const hasOther = !input && card.options.some((o) => o.kind === "OTHER");
  return (
    <div role="group" aria-label="Choose one" data-testid="decision-card" className="mt-2 flex max-w-[88%] flex-col gap-2 rounded-2xl px-3.5 py-3" style={{ border: "1px solid var(--warning-border)", background: "var(--bg-card)" }}>
      {real.map((o) => (
        <button
          key={o.key}
          type="button"
          disabled={disabled}
          data-testid={`card-option-${o.key}`}
          onClick={() => (o.form ? onOpenForm(o.form) : onAnswer({ id: messageId, option: o.key }, o.label))}
          className="mt-btn mt-focus flex flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left"
          style={{ border: `1px solid ${o.kind === "RECOMMENDED" ? "var(--accent-border-default)" : "var(--border-hover)"}`, color: "var(--text-2)", opacity: disabled ? 0.5 : 1 }}
        >
          <span className="flex items-center gap-2 t-body-sm font-semibold">
            {o.label}
            {o.kind === "RECOMMENDED" && <StatusBadge tone="accent">Recommended</StatusBadge>}
          </span>
          <span className="t-meta" style={{ color: "var(--text-5)" }}>{o.reason}</span>
        </button>
      ))}
      {input && (
        <div className="flex flex-wrap items-center justify-between gap-2 t-meta" style={{ color: "var(--text-5)" }}>
          <span>{real.length > 0 ? "Choose one, or type your answer in the chat bar below." : "Type your answer in the chat bar below."}</span>
          {cancel && (
            <button type="button" disabled={disabled} data-testid="card-cancel" onClick={() => onAnswer({ id: messageId, option: cancel.key }, "Cancel")} className="mt-focus rounded-lg px-2 py-1 t-meta font-bold" style={{ color: "var(--text-4)", border: "1px solid var(--border-subtle)" }}>
              Cancel
            </button>
          )}
        </div>
      )}
      {hasOther && !typing && (
        <button type="button" disabled={disabled} data-testid="card-option-other" onClick={() => setTyping(true)} className="mt-btn mt-focus self-start rounded-lg px-3 py-1.5 t-body-sm font-semibold" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)", opacity: disabled ? 0.5 : 1 }}>
          Other…
        </button>
      )}
      {hasOther && typing && (
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const text = other.trim();
            if (!text || disabled) return;
            onAnswer({ id: messageId, option: null }, text);
            setOther("");
            setTyping(false);
          }}
        >
          <input value={other} onChange={(e) => setOther(e.target.value)} maxLength={200} aria-label="Your own answer" className="mt-focus min-w-0 flex-1 rounded-lg bg-transparent px-2.5 py-1.5 t-body-sm" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }} />
          <button type="submit" disabled={disabled || !other.trim()} className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: disabled || !other.trim() ? 0.5 : 1 }}>
            Send
          </button>
        </form>
      )}
    </div>
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
          <button type="button" disabled={processing} onClick={() => setMode(mode === "resolve" ? "none" : "resolve")} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Resolve
          </button>
        )}
        {status === "RESOLVED" && (
          <button type="button" onClick={onReopen} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Reopen
          </button>
        )}
        <button type="button" disabled={processing} onClick={() => setMode(mode === "archive" ? "none" : "archive")} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
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
