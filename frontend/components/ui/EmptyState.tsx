import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

/** A designed "nothing here" — says what is missing and, where possible, what to do about it.
 * Used instead of ever showing placeholder numbers for data the backend hasn't produced. */
export function EmptyState({
  title,
  description,
  icon = "dot",
  action,
  compact = false,
}: {
  title: string;
  description?: ReactNode;
  icon?: IconName;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center"
      style={{ padding: compact ? "20px 16px" : "36px 24px" }}
    >
      <div
        className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl"
        style={{ background: "var(--fill-hover)", color: "var(--text-6)" }}
      >
        <Icon name={icon} size={18} />
      </div>
      <div className="t-body font-semibold" style={{ color: "var(--text-3)" }}>
        {title}
      </div>
      {description && (
        <div className="mt-1 max-w-[46ch] t-body-sm leading-relaxed" style={{ color: "var(--text-6)" }}>
          {description}
        </div>
      )}
      {action && <div className="mt-3.5">{action}</div>}
    </div>
  );
}
