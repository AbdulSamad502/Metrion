"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch, type DataRequestItem, type Layer1Alert, type Layer1AlertsResponse } from "@/lib/api";

/** One source's load state. `forbidden` is a real outcome, not an error: the signed-in role
 * simply lacks that agent's permission (403), so the feed shows nothing for it. */
export type FeedStatus = "loading" | "ok" | "forbidden" | "error";

export type NotificationsState = {
  alerts: Layer1Alert[];
  alertsStatus: FeedStatus;
  alertsError: string | null;
  dataRequests: DataRequestItem[];
  dataRequestsStatus: FeedStatus;
  dataRequestsError: string | null;
  /** Items worth a look right now: alerts in the window + data requests still open. This is NOT
   * an "unread" count — the backend has no read/unread state. */
  attentionCount: number;
  reload: () => void;
};

/** Days of CI alerts the feed covers. */
export const ALERT_WINDOW_DAYS = 14;

const isOpenRequest = (r: DataRequestItem) => !["RESOLVED", "FULFILLED", "CLOSED", "CANCELLED"].includes(r.status.toUpperCase());

/** The notifications feed, built ONLY from sources that exist:
 *  - `GET /ci/alerts` — Layer 1 competitor price/availability alerts
 *  - `GET /cfo/data-requests` — inputs the CFO asked the seller for
 * There is no notification service, so there is no read state, no impact figure and no
 * recommendation/system categories — nothing here is invented to fill that gap. */
export function useNotificationsFeed(enabled: boolean): NotificationsState {
  const { getToken } = useAuth();
  const [alerts, setAlerts] = useState<Layer1Alert[]>([]);
  const [alertsStatus, setAlertsStatus] = useState<FeedStatus>("loading");
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [dataRequests, setDataRequests] = useState<DataRequestItem[]>([]);
  const [dataRequestsStatus, setDataRequestsStatus] = useState<FeedStatus>("loading");
  const [dataRequestsError, setDataRequestsError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      const token = await getToken();
      const [a, d] = await Promise.allSettled([
        apiFetch<Layer1AlertsResponse>(`/api/v1/ci/alerts?days=${ALERT_WINDOW_DAYS}`, token),
        apiFetch<DataRequestItem[]>("/api/v1/cfo/data-requests", token),
      ]);
      if (cancelled) return;
      const settle = <T,>(
        r: PromiseSettledResult<T>,
        ok: (v: T) => void,
        status: (s: FeedStatus) => void,
        err: (m: string | null) => void,
      ) => {
        if (r.status === "fulfilled") {
          ok(r.value);
          status("ok");
          err(null);
        } else if (r.reason instanceof ApiError && r.reason.status === 403) {
          status("forbidden");
          err(null);
        } else {
          status("error");
          err(r.reason instanceof ApiError ? r.reason.message : "Could not reach the backend");
        }
      };
      settle(a, (v) => setAlerts(v.alerts), setAlertsStatus, setAlertsError);
      settle(d, setDataRequests, setDataRequestsStatus, setDataRequestsError);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce]);

  return {
    alerts,
    alertsStatus,
    alertsError,
    dataRequests,
    dataRequestsStatus,
    dataRequestsError,
    attentionCount: alerts.length + dataRequests.filter(isOpenRequest).length,
    reload,
  };
}

export { isOpenRequest };
