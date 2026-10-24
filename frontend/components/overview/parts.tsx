"use client";

import type { CSSProperties, ReactNode } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import "./overview.css";

/** Small pieces the redesigned dashboards share. Presentation only. */

/** Staggers a card's first rise: the nth card starts n × 56ms after the first. */
export const rise = (i: number): CSSProperties => ({ ["--i" as string]: i });

export function Pill({ tone, children, icon }: { tone?: "good" | "warn" | "bad" | "brand"; children: ReactNode; icon?: IconName }) {
  return (
    <span className={`ov-pill${tone ? ` ov-pill--${tone}` : ""}`}>
      {icon && <Icon name={icon} size={12} strokeWidth={2} />}
      {children}
    </span>
  );
}

/** A round refresh button. While it works the icon turns and the label says so. */
export function RefreshButton({ spinning, onClick, label = "Refresh" }: { spinning: boolean; onClick: () => void; label?: string }) {
  return (
    <button type="button" className="ov-icon-btn" onClick={onClick} disabled={spinning} aria-label={spinning ? "Refreshing…" : label} title={label}>
      <svg className={spinning ? "ov-spin" : undefined} width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M16.5 10a6.5 6.5 0 1 1-2-4.7" />
        <path d="M16.5 3.5v3.3h-3.3" />
      </svg>
    </button>
  );
}

/** A note with an optional action: warm for "heads up", red for "something failed". */
export function Note({ tone = "warn", children, action }: { tone?: "warn" | "bad"; children: ReactNode; action?: ReactNode }) {
  return (
    <div className={`ov-note${tone === "bad" ? " ov-note--bad" : ""}`} role={tone === "bad" ? "alert" : "status"}>
      <span>{children}</span>
      {action}
    </div>
  );
}

/** A failure in plain words, with a way to try again. Same look as the other notes; announced as an alert. */
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="ov-note ov-note--bad" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="ov-btn min-h-10" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

/** Soft placeholder lines while something loads. The words are for screen readers and for the test that waits on them. */
export function LoadingLines({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <span className="sr-only">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="ov-skel" style={{ height: 16, width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}
