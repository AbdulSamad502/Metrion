"use client";

import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ErrorBanner, LoadingLines, Pill as BasePill } from "@/components/overview/parts";
import { Spinner } from "@/components/ui/LoadingState";
import { useToast } from "@/components/ui/Toast";
import { explainShowcaseError } from "@/lib/cmoShowcase";
import "@/components/overview/overview.css";
import "./cmo.css";

/** Small read-only building blocks for the CMO showcase. Nothing here collects input except the search box and filters. */

export type Async<T> = { status: "loading" } | { status: "error"; message: string; notConfigured: boolean } | { status: "ready"; data: T };
export type AsyncView<T> = { state: Async<T>; reload: () => void; refreshing: boolean; refreshError: string | null };

/** Lets the page refresh every section at once (`key` changes), and know whether any section is still re-reading (`report`). A section outside a provider just never refreshes that way. */
const RefreshContext = createContext<{ key: number; report: (id: string, busy: boolean) => void }>({ key: 0, report: () => undefined });
export const ShowcaseRefreshProvider = RefreshContext.Provider;

/** Loads one section. A change of INPUTS (marketplace, product, search, view) shows the loading state, because the old results belong to other inputs and
 * must not stand in for the new ones. A RE-READ of the same inputs (retry, refresh) keeps what is on screen, says it is updating, and on failure keeps it and says so. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncView<T> {
  const { key: refreshKey, report } = useContext(RefreshContext);
  const [tick, setTick] = useState(0);
  type Done = { inputs: string; req: string; result: Exclude<Async<T>, { status: "loading" }>; refreshError: string | null };
  const [done, setDone] = useState<Done | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  });
  const inputs = JSON.stringify(deps.map((d) => (typeof d === "object" || typeof d === "function" ? "~" : d)));
  const req = `${inputs}#${tick}.${refreshKey}`;
  useEffect(() => {
    let live = true; // a reply that arrives after a newer request, or after the section is gone, is dropped
    loadRef.current().then(
      (data) => live && setDone({ inputs, req, result: { status: "ready", data }, refreshError: null }),
      (e) => {
        if (!live) return;
        const problem = explainShowcaseError(e);
        setDone((prev) =>
          prev && prev.inputs === inputs && prev.result.status === "ready"
            ? { ...prev, req, refreshError: problem.message } // keep the last results that loaded
            : { inputs, req, result: { status: "error", ...problem }, refreshError: null },
        );
      },
    );
    return () => {
      live = false;
    };
  }, [inputs, req]);
  const same = done !== null && done.inputs === inputs;
  const refreshing = same && done.req !== req;
  const id = useId();
  useEffect(() => {
    report(id, refreshing);
    return () => report(id, false);
  }, [report, id, refreshing]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { state: same ? done.result : { status: "loading" }, reload, refreshing, refreshError: same ? done.refreshError : null };
}

/** Renders the loading / error / empty / ready states distinctly, and keeps ready results on screen while they are re-read or when a re-read fails. */
export function AsyncBlock<T>({ a, isEmpty, empty, label, children }: {
  a: AsyncView<T>; isEmpty: (d: T) => boolean; empty: ReactNode; label: string; children: (d: T) => ReactNode;
}) {
  const { state, reload, refreshing, refreshError } = a;
  if (state.status === "loading" || (state.status === "error" && refreshing)) return <LoadingLines lines={3} label={`Loading ${label}`} />;
  if (state.status === "error") return state.notConfigured ? <Hint>{state.message}</Hint> : <ErrorBanner message={state.message} onRetry={reload} />;
  return (
    <div aria-busy={refreshing}>
      {refreshError && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBanner message={`${refreshError} Showing the last ${label} that loaded.`} onRetry={reload} />
        </div>
      )}
      {refreshing && (
        <p role="status" className="ov-meta" style={{ marginBottom: 16, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Spinner size={12} /> Updating {label}…
        </p>
      )}
      <div style={{ opacity: refreshing ? 0.6 : 1 }}>{isEmpty(state.data) ? <Hint>{empty}</Hint> : children(state.data)}</div>
    </div>
  );
}

/** "21 / 200 chars", or, when the verified source states no limit, "21 chars · no limit stated" (never a blank or "null"). */
export const withLimit = (n: number, max: number | null | undefined, unit: string): string => (max == null ? `${n} ${unit} · no limit stated` : `${n} / ${max} ${unit}`);

export function Hint({ children }: { children: ReactNode }) {
  return (
    <p className="cmo-hint" role="status">
      {children}
    </p>
  );
}

export function Pill({ children, tone = "neutral", title }: { children: ReactNode; tone?: "accent" | "neutral" | "warning"; title?: string }) {
  return (
    <span title={title}>
      <BasePill tone={tone === "accent" ? "brand" : tone === "warning" ? "warn" : undefined}>{children}</BasePill>
    </span>
  );
}

export function Card({ children, accent = false, className = "" }: { children: ReactNode; accent?: boolean; className?: string }) {
  return <div className={`cmo-card${accent ? " cmo-card--accent" : ""} ${className}`}>{children}</div>;
}

/** A thin bar for "how much of the limit this uses". Decorative: the numbers beside it say the same thing, so it is hidden from screen readers. */
export function LengthMeter({ n, max }: { n: number; max: number | null | undefined }) {
  if (max == null || max <= 0) return null;
  return (
    <span className="cmo-meter" aria-hidden>
      <i style={{ width: `${Math.min(100, (n / max) * 100)}%` }} />
    </span>
  );
}

export function SectionCard({ title, hint, action, children }: { title: string; hint?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="ov-card ov-rise" aria-label={title}>
      <header className="ov-card-head" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="min-w-0">
          <h2 className="ov-title">{title}</h2>
          {hint && <p className="ov-meta" style={{ marginTop: 4 }}>{hint}</p>}
        </div>
        {action && <div style={{ display: "flex", alignItems: "center", gap: 8 }}>{action}</div>}
      </header>
      {children}
    </section>
  );
}

/** Copies text to the clipboard; `onCopied` (fire-and-forget usage event) runs only after a successful copy. */
export function CopyButton({ text, label = "Copy", onCopied, primary = false }: { text: string; label?: string; onCopied?: () => void; primary?: boolean }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // clipboard refused: nothing is shown as copied and no event is recorded, and the seller is told, so they can select the text themselves
      toast.error("Could not copy. Select the text and copy it yourself.");
      return;
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
      className={`ov-btn min-h-10${primary ? " ov-btn--brand" : ""}`}
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
