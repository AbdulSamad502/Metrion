import type { ReactNode } from "react";

export type Tone = "accent" | "warning" | "negative" | "info" | "neutral";

const TONES: Record<Tone, { color: string; bg: string; border: string }> = {
  accent: { color: "var(--accent)", bg: "var(--accent-fill-default)", border: "var(--accent-border-subtle)" },
  warning: { color: "var(--warning)", bg: "var(--warning-fill)", border: "var(--warning-border)" },
  negative: { color: "var(--negative)", bg: "var(--negative-fill)", border: "transparent" },
  info: { color: "var(--info)", bg: "var(--info-fill)", border: "var(--info-border)" },
  neutral: { color: "var(--text-inactive)", bg: "var(--fill-hover)", border: "transparent" },
};

/** Compact status pill with an optional leading dot. Color is never the only signal — callers
 * always pass a text label. `title` carries the longer explanation for hover/assistive tech. */
export function StatusBadge({
  tone,
  children,
  dot = false,
  title,
}: {
  tone: Tone;
  children: ReactNode;
  dot?: boolean;
  title?: string;
}) {
  const t = TONES[tone];
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1.5 whitespace-nowrap t-micro rounded-lg px-2 py-0.5"
      style={{ color: t.color, background: t.bg, border: `1px solid ${t.border}` }}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full" style={{ background: t.color }} aria-hidden />}
      {children}
    </span>
  );
}
