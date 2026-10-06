"use client";

import { useCallback, useId, useRef, useState, type ReactNode } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { explainCmoError, type CmoProblem } from "@/lib/cmo";

/** Small form + feedback primitives for the CMO workspace (same inline CSS-variable convention the CFO / PI pages use). */

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block t-body-sm" style={{ color: "var(--text-6)" }}>
        {label}
      </label>
      {children(id)}
      {hint && !error && (
        <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>
          {hint}
        </div>
      )}
      {error && (
        <div role="alert" className="mt-1 t-meta" style={{ color: "var(--negative)" }}>
          {error}
        </div>
      )}
    </div>
  );
}

export function TextInput({
  id, value, onChange, placeholder, inputMode, maxLength, invalid,
}: {
  id?: string; value: string; onChange: (v: string) => void; placeholder?: string; inputMode?: "text" | "decimal"; maxLength?: number; invalid?: boolean;
}) {
  return (
    <input
      id={id}
      type="text"
      value={value}
      inputMode={inputMode}
      maxLength={maxLength}
      aria-invalid={invalid || undefined}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
    />
  );
}

export function TextArea({ id, value, onChange, placeholder, rows = 3, maxLength }: { id?: string; value: string; onChange: (v: string) => void; placeholder?: string; rows?: number; maxLength?: number }) {
  return (
    <textarea id={id} value={value} rows={rows} maxLength={maxLength} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="mt-input w-full rounded-lg px-3 py-2 t-body" />
  );
}

export function SelectInput({ id, value, onChange, options }: { id?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="mt-input w-full rounded-lg px-3 py-2 t-body">
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function SubmitButton({
  onClick, busy, label, busyLabel, primary = false, disabled = false, title,
}: {
  onClick: () => void; busy: boolean; label: string; busyLabel: string; primary?: boolean; disabled?: boolean; title?: string;
}) {
  const off = busy || disabled;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={off}
      title={title}
      aria-busy={busy || undefined}
      className={`mt-btn mt-focus w-fit rounded-lg px-4 py-2 t-body font-bold disabled:cursor-not-allowed ${primary ? "" : "mt-btn-secondary"}`}
      style={primary ? { background: "var(--accent)", color: "var(--accent-on-fill)", opacity: off ? 0.6 : 1 } : { opacity: off ? 0.6 : 1 }}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

/** A plain-words explanation of a failed call: what happened, what it means, and that nothing was charged where that is true. */
export function ProblemNotice({ problem, onRetry }: { problem: CmoProblem | null; onRetry?: () => void }) {
  if (!problem) return null;
  const tone = problem.kind === "quota" || problem.kind === "config" || problem.kind === "changed" || problem.kind === "busy" ? "var(--warning)" : "var(--negative)";
  const fill = problem.kind === "quota" || problem.kind === "config" || problem.kind === "changed" || problem.kind === "busy" ? "var(--warning-fill)" : "var(--negative-fill)";
  return (
    <div role="alert" className="rounded-xl px-3.5 py-2.5 t-body-sm" style={{ background: fill, color: tone }}>
      <div className="font-bold">{problem.title}</div>
      <div className="mt-0.5" style={{ color: "var(--text-3)" }}>
        {problem.body}
      </div>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-btn mt-focus mt-2 rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: `1px solid ${tone}`, color: tone }}>
          Try again
        </button>
      )}
    </div>
  );
}

/** One in-flight call at a time: `run(fn)` ignores a second click while busy (no double submit), keeps the last result, and turns
 * any failure into a `CmoProblem` the seller can read. */
export function useAction<T>() {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<CmoProblem | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const inFlight = useRef(false);
  const run = useCallback(async (fn: () => Promise<T>): Promise<T | null> => {
    if (inFlight.current) return null;
    inFlight.current = true;
    setBusy(true);
    setProblem(null);
    try {
      const r = await fn();
      setResult(r);
      return r;
    } catch (e) {
      setProblem(explainCmoError(e));
      return null;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, []);
  const reset = useCallback(() => {
    setResult(null);
    setProblem(null);
  }, []);
  return { busy, problem, result, run, reset, setResult };
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 1800);
  };
  return (
    <button type="button" onClick={copy} className="mt-btn mt-btn-secondary mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" aria-live="polite">
      {state === "done" ? "Copied" : state === "failed" ? "Copy failed" : label}
    </button>
  );
}

export function ChoiceChips<T extends string>({
  options, value, onChange, label,
}: {
  options: { id: T; label: string }[]; value: T[]; onChange: (v: T[]) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = value.includes(o.id);
        return (
          <button
            key={o.id}
            type="button"
            role="checkbox"
            aria-checked={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o.id) : [...value, o.id])}
            className="mt-chip mt-focus rounded-lg px-3 py-1.5 t-body-sm font-semibold"
            style={on ? { background: "var(--accent-fill-default)", color: "var(--accent)", border: "1px solid var(--accent-border-subtle)" } : { border: "1px solid var(--border-hover)", color: "var(--text-5)" }}
          >
            {on ? "✓ " : ""}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function RecommendOnlyNote() {
  return (
    <p className="t-meta" style={{ color: "var(--text-6)" }}>
      Recommend-only: Metrion never publishes or changes anything on a marketplace. Copy the text and paste it into your seller panel yourself.
    </p>
  );
}

export function Unit({ n, what }: { n: number; what: string }) {
  return (
    <StatusBadge tone={n > 0 ? "info" : "neutral"} title={`${n} unit(s) of your plan were used for this ${what}`}>
      {n} {n === 1 ? "unit" : "units"} used
    </StatusBadge>
  );
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "date unknown" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
