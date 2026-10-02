import type { ReactNode } from "react";
import { Card } from "./Card";
import { LoadingState } from "./LoadingState";

/** One headline figure. The value is ALWAYS supplied by the caller from a real response — this
 * component never formats, derives or defaults a number. `value === null` renders an explicit
 * "Not available" with the reason, never a zero or a placeholder. */
export function MetricCard({
  label,
  value,
  hint,
  unavailableReason = "Not available yet",
  loading = false,
  tone = "default",
  footer,
}: {
  label: string;
  value: string | null;
  hint?: ReactNode;
  unavailableReason?: string;
  loading?: boolean;
  tone?: "default" | "positive" | "negative";
  footer?: ReactNode;
}) {
  const color = tone === "positive" ? "var(--accent)" : tone === "negative" ? "var(--negative)" : "var(--text-1)";
  return (
    <Card className="p-5">
      <div className="t-label" style={{ color: "var(--text-5)" }}>
        {label}
      </div>
      <div className="mt-2.5">
        {loading ? (
          <LoadingState lines={1} label={`Loading ${label}`} />
        ) : value === null ? (
          <>
            <div className="t-headline font-semibold" style={{ color: "var(--text-6)" }}>
              Not available
            </div>
            <div className="mt-1 t-meta-sm" style={{ color: "var(--text-7)" }}>
              {unavailableReason}
            </div>
          </>
        ) : (
          <div className="t-metric" style={{ color }}>
            {value}
          </div>
        )}
      </div>
      {hint && !loading && value !== null && (
        <div className="mt-2 t-meta" style={{ color: "var(--text-5)" }}>
          {hint}
        </div>
      )}
      {footer && <div className="mt-3">{footer}</div>}
    </Card>
  );
}
