import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { LoadingState } from "./LoadingState";

/** An inline metric — a figure with a label and no box around it. Used in strips where several
 * numbers share one surface. Same contract as `MetricCard`: the value is supplied by the caller from
 * a real response; `null` renders "Not available" with a reason, never a zero. */
export function Stat({
  label,
  value,
  hint,
  loading = false,
  tone = "default",
  unavailableReason = "Not available yet",
  href,
}: {
  label: string;
  value: string | null;
  hint?: ReactNode;
  loading?: boolean;
  tone?: "default" | "warning" | "negative";
  unavailableReason?: string;
  /** Where this number is explained in full — makes the stat a real link. Omit if nowhere real. */
  href?: string;
}) {
  const color = tone === "negative" ? "var(--negative)" : tone === "warning" ? "var(--warning)" : "var(--text-1)";
  const body = (
    <>
      <div className="mt-eyebrow">{label}</div>
      <div className="mt-2">
        {loading ? (
          <LoadingState lines={1} label={`Loading ${label}`} />
        ) : value === null ? (
          <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
            Not available — {unavailableReason}
          </div>
        ) : (
          <div className="t-metric-lg" style={{ color }}>
            {value}
          </div>
        )}
      </div>
      {hint && !loading && (
        <div className="t-meta mt-1.5" style={{ color: "var(--text-5)" }}>
          {hint}
        </div>
      )}
      {href && !loading && (
        <span className="mt-card-cta t-meta mt-2 inline-flex items-center gap-1 font-semibold">
          Details <Icon name="arrow" size={11} strokeWidth={1.9} />
        </span>
      )}
    </>
  );
  const cell = "min-w-0 px-5 py-4 first:pl-0";
  return href ? (
    <Link href={href} className={`${cell} mt-row mt-focus mt-dash-card--interactive-lite block`}>
      {body}
    </Link>
  ) : (
    <div className={cell}>{body}</div>
  );
}
