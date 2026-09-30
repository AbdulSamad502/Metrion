"use client";

/** Shared honesty-labeling badge — PI's deliberate deviation from CI/CFO's "duplicate
 * inline" convention (see `frontend/app/dashboard/ceo-hub/page.tsx`'s `FieldSourceBadge`
 * for the nearest precedent this generalizes). PI's whole design (docs/planning PI build
 * plan §0) is built around never blurring estimate-vs-confirmed, commentary-vs-review, or
 * candidate-vs-bestseller distinctions, and these labels repeat across many backend fields
 * (`opportunity_label`, `cogs_basis`, `insight_source_type`, `proxy_state`,
 * `web_price_signal.status`, `demand_signal.status`) — worth one shared component instead
 * of reimplementing the same three-color mapping per section.
 *
 * `status` groups every one of those fields into three tiers:
 * - "unavailable"  — nothing was obtained; muted, never implies a hidden failure (--text-6)
 * - "gap"          — a hard, seller-visible gap that needs action, e.g. MOQ not published,
 *                    a UNKNOWN cogs_basis batch quantity (--negative)
 * - "available"    — confirmed / seller-entered / computed data (--accent)
 *
 * `reason`, when present, always renders — this component never lets a bare status word
 * stand alone without its disclaimer/explanation, per §0's "never just a bare number" rule.
 */
export function ConfidenceBadge({
  status,
  label,
  reason,
}: {
  status: "available" | "unavailable" | "gap";
  label: string;
  reason?: string | null;
}) {
  const color = status === "available" ? "var(--accent)" : status === "gap" ? "var(--negative)" : "var(--text-6)";
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span className="text-[12px] font-semibold" style={{ color }}>
        {label}
      </span>
      {reason && (
        <span className="text-[11px]" style={{ color: "var(--text-7)" }}>
          {reason}
        </span>
      )}
    </span>
  );
}
