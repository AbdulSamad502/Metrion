"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { ClarificationCard, ClarificationReply } from "@/lib/ceo";
import { parseProgress } from "@/lib/clarificationProgress";

const MAX_OTHER = 200;

/** The CEO's question card (specs 6.32 / 6.34). Everything on it is what the backend sent: the options (real candidates built from the seller's own
 * data, the recommended one first with the rule that recommends it), and, only when the backend offers them, Back (step back one question), Skip (an
 * option that records "unknown" on purpose) and Cancel. Nothing is invented and nothing is chosen for the seller.
 *
 * A choice is STAGED first and sent with Continue, so a mis-click costs nothing; the typed "Other" text is kept while the seller changes their mind.
 * The protocol is single-answer per question (a reply carries one option key or one typed text), so there is no multi-select here: it would need the
 * backend to declare a multi-valued slot first (docs/design/ui-ux-phase3-clarification.md). */
export function DecisionCard({
  messageId, question, card, disabled, onAnswer, onOpenForm,
}: {
  messageId: string;
  question: string;
  card: ClarificationCard;
  disabled: boolean;
  onAnswer: (reply: ClarificationReply, text: string) => void;
  onOpenForm: (form: string) => void;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const input = card.kind === "INPUT"; // the answer may also be typed in the chat bar
  const real = card.options.filter((o) => o.kind !== "OTHER" && o.kind !== "CANCEL" && o.kind !== "BACK" && !o.skip);
  const skip = card.options.find((o) => o.skip);
  const back = card.options.find((o) => o.kind === "BACK");
  const cancel = card.options.find((o) => o.kind === "CANCEL");
  const hasOther = !input && card.options.some((o) => o.kind === "OTHER");
  const progress = parseProgress(question);
  const typed = other.trim();
  const otherPicked = picked === "other";
  const canContinue = !disabled && (otherPicked ? typed.length > 0 && typed.length <= MAX_OTHER : picked !== null);

  const send = () => {
    if (!canContinue) return;
    if (otherPicked) {
      onAnswer({ id: messageId, option: null }, typed);
      return;
    }
    const o = real.find((x) => x.key === picked);
    if (o) onAnswer({ id: messageId, option: o.key }, o.label);
  };
  const act = (key: string, label: string) => {
    if (!disabled) onAnswer({ id: messageId, option: key }, label);
  };

  return (
    <div
      data-testid="decision-card"
      className="mt-2 flex max-w-[92%] flex-col gap-3 rounded-2xl px-4 py-3.5"
      style={{ border: "1px solid var(--warning-border)", background: "var(--bg-card)" }}
    >
      {progress && (
        <div data-testid="card-progress" className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between t-meta" style={{ color: "var(--text-4)" }}>
            <span className="font-semibold">Question {progress.step} of {progress.total}</span>
            <span>{progress.total === progress.step ? "Last question" : "More to follow"}</span>
          </div>
          <div role="progressbar" aria-label="Questions answered" aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.step - 1} className="h-1 w-full overflow-hidden rounded-full" style={{ background: "var(--border-subtle)" }}>
            <div className="h-full rounded-full" style={{ width: `${progress.percent}%`, background: "var(--accent)", transition: "width 0.2s ease" }} />
          </div>
        </div>
      )}

      {(real.length > 0 || hasOther) && (
        <div role="radiogroup" aria-label="Choose one" className="flex flex-col gap-2">
          {real.map((o) => (
            <label
              key={o.key}
              data-testid={`card-option-${o.key}`}
              className="mt-btn mt-focus flex cursor-pointer flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left"
              style={{
                border: `1px solid ${picked === o.key ? "var(--accent-border-strong)" : o.kind === "RECOMMENDED" ? "var(--accent-border-default)" : "var(--border-hover)"}`,
                background: picked === o.key ? "var(--accent-fill-subtle)" : "transparent",
                color: "var(--text-2)", opacity: disabled ? 0.5 : 1,
              }}
              onClick={(e) => {
                if (o.form) { e.preventDefault(); if (!disabled) onOpenForm(o.form); }
              }}
            >
              <span className="flex items-center gap-2 t-body-sm font-semibold">
                <input
                  type="radio" name={`card-${messageId}`} value={o.key} disabled={disabled} checked={picked === o.key} className="accent-[var(--accent)]"
                  onChange={() => { if (!o.form) setPicked(o.key); }}
                />
                {o.label}
                {o.kind === "RECOMMENDED" && <StatusBadge tone="accent">Recommended</StatusBadge>}
              </span>
              <span className="t-meta pl-6" style={{ color: "var(--text-5)" }}>{o.reason}</span>
            </label>
          ))}
          {hasOther && (
            <label
              data-testid="card-option-other"
              className="mt-btn mt-focus flex cursor-pointer flex-col gap-1.5 rounded-lg px-3 py-2"
              style={{ border: `1px solid ${otherPicked ? "var(--accent-border-strong)" : "var(--border-subtle)"}`, background: otherPicked ? "var(--accent-fill-subtle)" : "transparent", color: "var(--text-3)", opacity: disabled ? 0.5 : 1 }}
            >
              <span className="flex items-center gap-2 t-body-sm font-semibold">
                <input type="radio" name={`card-${messageId}`} value="other" disabled={disabled} checked={otherPicked} onChange={() => setPicked("other")} className="accent-[var(--accent)]" />
                Other…
              </span>
              {otherPicked && (
                <span className="flex flex-col gap-1 pl-6">
                  <input
                    autoFocus value={other} maxLength={MAX_OTHER} disabled={disabled} aria-label="Your own answer"
                    onChange={(e) => setOther(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); send(); } }}
                    className="mt-focus min-w-0 rounded-lg bg-transparent px-2.5 py-1.5 t-body-sm" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
                  />
                  <span className="t-meta" style={{ color: "var(--text-5)" }}>
                    {typed.length === 0 ? "Type your answer to continue." : `${typed.length}/${MAX_OTHER}`}
                  </span>
                </span>
              )}
            </label>
          )}
        </div>
      )}

      {input && (
        <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>
          {real.length > 0 ? "Choose one and continue, or type your answer in the chat bar below." : "Type your answer in the chat bar below."}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {back && (
          <button type="button" disabled={disabled} data-testid="card-back" title={back.reason} onClick={() => act(back.key, back.label)} className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-body-sm font-semibold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)", opacity: disabled ? 0.5 : 1 }}>
            Back
          </button>
        )}
        {cancel && (
          <button type="button" disabled={disabled} data-testid="card-cancel" title={cancel.reason} onClick={() => act(cancel.key, "Cancel")} className="mt-focus rounded-lg px-3 py-1.5 t-body-sm font-semibold" style={{ color: "var(--text-4)", border: "1px solid var(--border-subtle)", opacity: disabled ? 0.5 : 1 }}>
            Cancel
          </button>
        )}
        <span className="flex-1" />
        {skip && (
          <button type="button" disabled={disabled} data-testid="card-skip" title={skip.reason} onClick={() => act(skip.key, skip.label)} className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-body-sm font-semibold" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)", opacity: disabled ? 0.5 : 1 }}>
            Skip · {skip.label}
          </button>
        )}
        {(real.length > 0 || hasOther) && (
          <button type="button" disabled={!canContinue} data-testid="card-continue" onClick={send} className="mt-btn mt-focus rounded-lg px-4 py-1.5 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: canContinue ? 1 : 0.5 }}>
            Continue
          </button>
        )}
      </div>
      {skip && (
        <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>
          Skipping records “{skip.label}”: {skip.reason}
        </p>
      )}
    </div>
  );
}
