"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { CeoMessage, ExplicitPeriod, InvestigationDetail, TurnRow } from "@/lib/ceo";
import { investigationTitle, messageView, validatePeriod, type HubState } from "@/lib/ceoModel";
import type { TurnProgress } from "@/lib/useCeoHub";

const todayIso = () => new Date().toISOString().slice(0, 10);

/** CENTER: the CEO conversation, the investigation's status and the composer.
 *
 * Everything shown as the CEO's words is the backend's stored, safety-gated message. The date range is an explicit control: when set,
 * it is sent with the question and the backend uses it as THE period: the model never chooses it. The "ideas" chips only fill the
 * composer; they send nothing. */
export function Conversation({
  state,
  detail,
  turn,
  notice,
  onDismissNotice,
  onSend,
  onResolve,
  onReopen,
  onArchive,
  onRetry,
}: {
  state: HubState;
  detail: InvestigationDetail | null;
  turn: TurnProgress;
  notice: string | null;
  onDismissNotice: () => void;
  onSend: (message: string, period: ExplicitPeriod | null) => void;
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
    <div className="flex min-h-0 flex-col gap-4" data-testid="conversation" data-state={state}>
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

      <Thread messages={detail.messages} turnById={turnById} isNew={state === "NEW"} />

      {state === "PROCESSING" && <Processing question={turn.question} arrived={turn.arrivedIds.length} />}
      {turn.error && state !== "PROCESSING" && <ErrorNotice message={turn.error} />}

      {!closed && <Composer disabled={state === "PROCESSING"} onSend={onSend} isNew={state === "NEW"} />}
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

function Processing({ question, arrived }: { question: string | null; arrived: number }) {
  return (
    <div role="status" aria-live="polite" data-testid="processing" className="flex items-center gap-3 rounded-xl px-3.5 py-3 t-body-sm" style={{ border: "1px dashed var(--accent-border-default)", color: "var(--text-3)" }}>
      <Spinner />
      <span className="min-w-0 flex-1">
        The CEO is working on {question ? <>&ldquo;{question}&rdquo;</> : "your question"}.{" "}
        {arrived > 0 ? `${arrived} ${arrived === 1 ? "finding has" : "findings have"} arrived so far; see the panel on the right.` : "Findings appear on the right as each specialist finishes."}
      </span>
    </div>
  );
}

function Thread({ messages, turnById, isNew }: { messages: CeoMessage[]; turnById: Map<string, TurnRow>; isNew: boolean }) {
  const end = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);
  if (messages.length === 0) {
    return (
      <EmptyState
        compact
        icon="ceo"
        title={isNew ? "New investigation" : "No messages yet"}
        description="Ask a question below. If it needs a period, pick the dates yourself: the CEO never guesses a date range. It reads your saved results and runs only the specialists wired in above."
      />
    );
  }
  return (
    <ol className="m-0 flex max-h-[520px] list-none flex-col gap-3 overflow-y-auto p-0 pr-1" aria-label="Conversation" aria-live="polite">
      {messages.map((m) => (
        <li key={m.id}>
          <Bubble message={m} turnById={turnById} />
        </li>
      ))}
      <div ref={end} />
    </ol>
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

const IDEAS = ["Why did my profit drop?", "Am I being paid what I am owed?", "Give me my business briefing", "What should I focus on this month?"];

function Composer({ disabled, isNew, onSend }: { disabled: boolean; isNew: boolean; onSend: (message: string, period: ExplicitPeriod | null) => void }) {
  const [text, setText] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const today = useMemo(() => todayIso(), []);
  const periodError = validatePeriod(start, end, today);
  const period: ExplicitPeriod | null = start && end && !periodError ? { start, end } : null;
  const canSend = !disabled && text.trim().length > 0 && !periodError;

  return (
    <form
      className="flex flex-col gap-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSend) return;
        onSend(text.trim(), period);
        setText("");
      }}
    >
      {isNew && (
        <div className="flex flex-wrap gap-2" aria-label="Question ideas">
          {IDEAS.map((idea) => (
            <button key={idea} type="button" onClick={() => setText(idea)} className="mt-chip mt-focus rounded-lg px-2.5 py-1 t-meta" style={{ color: "var(--text-4)", border: "1px solid var(--border-subtle)" }}>
              {idea}
            </button>
          ))}
        </div>
      )}
      <fieldset className="m-0 flex flex-wrap items-end gap-3 border-0 p-0">
        <legend className="mb-1 p-0 t-meta" style={{ color: "var(--text-5)" }}>
          Period (optional). If you set one, the CEO uses exactly these dates.
        </legend>
        <label className="flex flex-col gap-1 t-meta" style={{ color: "var(--text-5)" }}>
          From
          <input type="date" value={start} max={today} onChange={(e) => setStart(e.target.value)} className="mt-focus rounded-lg bg-transparent px-2 py-1.5 t-body-sm" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }} />
        </label>
        <label className="flex flex-col gap-1 t-meta" style={{ color: "var(--text-5)" }}>
          To
          <input type="date" value={end} max={today} onChange={(e) => setEnd(e.target.value)} className="mt-focus rounded-lg bg-transparent px-2 py-1.5 t-body-sm" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }} />
        </label>
        {(start || end) && (
          <button type="button" onClick={() => { setStart(""); setEnd(""); }} className="mt-btn mt-focus rounded-lg px-2.5 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
            Clear period
          </button>
        )}
      </fieldset>
      {periodError && (
        <div role="alert" className="t-meta" style={{ color: "var(--negative)" }}>
          {periodError}
        </div>
      )}
      <div className="flex items-end gap-2.5 rounded-2xl px-3.5 py-2.5" style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
          rows={2}
          maxLength={4000}
          disabled={disabled}
          aria-label="Ask the CEO"
          placeholder="Ask the CEO, for example “Why did my margin drop?”"
          className="mt-focus min-w-0 flex-1 resize-none bg-transparent t-body outline-none"
          style={{ color: "var(--text-2)" }}
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send"
          className="mt-btn mt-focus flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: canSend ? 1 : 0.5 }}
        >
          {disabled ? <Spinner /> : <Icon name="arrow" size={15} />}
        </button>
      </div>
    </form>
  );
}
