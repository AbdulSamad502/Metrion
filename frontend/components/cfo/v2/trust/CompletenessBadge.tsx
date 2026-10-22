import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Completeness } from "@/lib/cfoV2/types";
import { COMPLETENESS_VIEW } from "./formatStates";

/** The completeness chip for a figure. Wording and tone come from one table; the title carries the longer meaning. */
export function CompletenessBadge({ completeness }: { completeness: Completeness }) {
  const v = COMPLETENESS_VIEW[completeness];
  return (
    <StatusBadge tone={v.tone} dot title={v.meaning}>
      {v.label}
    </StatusBadge>
  );
}
