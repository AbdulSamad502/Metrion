"use client";

import Link from "next/link";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useShell } from "@/lib/ShellContext";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

/** Header-centre context chips. Each one reads from the shared notifications feed and renders
 * nothing at all when there is nothing to say — the header never carries filler. */
export function HeaderContext({ kind }: { kind: "requests" | "alerts" | "both" }) {
  const { notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const showRequests = kind !== "alerts" && requests > 0;
  const showAlerts = kind !== "requests" && alerts > 0;
  if (!showRequests && !showAlerts) return null;
  return (
    <div className="flex items-center gap-2">
      {showRequests && (
        <Link href="/dashboard/cfo#anomalies" className="mt-focus rounded-lg" title="Open the CFO's data requests">
          <StatusBadge tone="warning" dot>
            {requests} open data {requests === 1 ? "request" : "requests"}
          </StatusBadge>
        </Link>
      )}
      {showAlerts && (
        <Link href="/dashboard/notifications#alerts" className="mt-focus rounded-lg" title={`Competitor alerts in the last ${ALERT_WINDOW_DAYS} days`}>
          <StatusBadge tone="info" dot>
            {alerts} competitor {alerts === 1 ? "alert" : "alerts"}
          </StatusBadge>
        </Link>
      )}
    </div>
  );
}
