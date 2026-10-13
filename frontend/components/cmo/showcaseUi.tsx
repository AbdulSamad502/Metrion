"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { explainShowcaseError } from "@/lib/cmoShowcase";

/** Small read-only building blocks for the CMO showcase. Nothing here collects input except the search box and filters. */

export type Async<T> = { status: "loading" } | { status: "error"; message: string; notConfigured: boolean } | { status: "ready"; data: T };

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): { state: Async<T>; reload: () => void } {
  const [tick, setTick] = useState(0);
  const [done, setDone] = useState<{ run: string; result: Exclude<Async<T>, { status: "loading" }> } | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });
  const run = JSON.stringify([...deps.map((d) => (typeof d === "object" || typeof d === "function" ? "~" : d)), tick]);
  const depsKey = run;
  useEffect(() => {
    let live = true;
    loadRef.current().then(
      (data) => live && setDone({ run: depsKey, result: { status: "ready", data } }),
      (e) => live && setDone({ run: depsKey, result: { status: "error", ...explainShowcaseError(e) } }),
    );
    return () => {
      live = false;
    };
  }, [depsKey]);
  const state: Async<T> = done && done.run === run ? done.result : { status: "loading" };
  return { state, reload: useCallback(() => setTick((n) => n + 1), []) };
}

/** Renders the loading / error / empty / ready states distinctly. `isEmpty` decides the empty state; `empty` is its honest message. */
export function AsyncBlock<T>({ state, reload, isEmpty, empty, label, children }: {
  state: Async<T>; reload: () => void; isEmpty: (d: T) => boolean; empty: ReactNode; label: string; children: (d: T) => ReactNode;
}) {
  if (state.status === "loading") return <LoadingState lines={3} label={`Loading ${label}`} />;
  if (state.status === "error") return state.notConfigured ? <Hint>{state.message}</Hint> : <ErrorNotice message={state.message} onRetry={reload} />;
  if (isEmpty(state.data)) return <Hint>{empty}</Hint>;
  return <>{children(state.data)}</>;
}

export function Hint({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg px-3 py-3 t-body-sm" role="status" style={{ color: "var(--text-6)", background: "var(--fill-hover)", border: "1px dashed var(--border-default)" }}>
      {children}
    </p>
  );
}

export function Pill({ children, tone = "neutral", title }: { children: ReactNode; tone?: "accent" | "neutral" | "warning"; title?: string }) {
  const c = tone === "accent" ? "var(--accent)" : tone === "warning" ? "var(--warning)" : "var(--text-5)";
  return (
    <span title={title} className="t-micro inline-block whitespace-nowrap rounded px-1.5 py-0.5 font-bold uppercase" style={{ color: c, border: `1px solid ${tone === "accent" ? "var(--accent-border-default)" : "var(--border-default)"}`, background: tone === "accent" ? "var(--accent-fill-subtle)" : "transparent" }}>
      {children}
    </span>
  );
}

export function Card({ children, accent = false, className = "" }: { children: ReactNode; accent?: boolean; className?: string }) {
  return (
    <div className={`rounded-xl p-3.5 ${className}`} style={{ background: "var(--bg-card)", border: `1px solid ${accent ? "var(--accent-border-strong)" : "var(--border-subtle)"}` }}>
      {children}
    </div>
  );
}

export function SectionCard({ title, hint, action, children }: { title: string; hint?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-5" style={{ background: "var(--bg-card)", border: "1px solid var(--accent-border-subtle)" }} aria-label={title}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 t-card-title font-bold" style={{ color: "var(--text-1)" }}>
            <span className="h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} aria-hidden />
            {title}
          </h2>
          {hint && <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{hint}</p>}
        </div>
        {action && <div className="flex items-center gap-2">{action}</div>}
      </header>
      {children}
    </section>
  );
}

/** Copies text to the clipboard; `onCopied` (fire-and-forget usage event) runs only after a successful copy. */
export function CopyButton({ text, label = "Copy", onCopied, primary = false }: { text: string; label?: string; onCopied?: () => void; primary?: boolean }) {
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return; // clipboard refused: show nothing as copied, and record no event
    }
    setDone(true);
    onCopied?.();
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setDone(false), 1600);
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="mt-btn mt-focus min-h-[32px] rounded-lg px-3 py-1 t-meta font-bold"
      style={primary ? { background: "var(--accent)", color: "var(--accent-on-fill)" } : { border: "1px solid var(--border-hover)", color: "var(--text-2)" }}
      aria-label={done ? "Copied" : label}
    >
      {done ? "Copied" : label}
    </button>
  );
}

export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "not stated";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "not stated" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
