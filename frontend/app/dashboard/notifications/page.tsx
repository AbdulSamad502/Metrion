"use client";

import { PAGE_COPY } from "@/lib/navigation";
import Link from "next/link";
import { useState } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { EvidenceStateBadge, evidenceStateForTier } from "@/components/ui/EvidenceStateBadge";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import type { DataRequestItem, Layer1Alert } from "@/lib/api";
import { useShell } from "@/lib/ShellContext";
import { useHashTab } from "@/lib/useHashTab";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";

const TABS = [
  { id: "all", label: "All" },
  { id: "alerts", label: "Competitor alerts" },
  { id: "requests", label: "Data requests" },
] as const;

/** What is open in the drawer is remembered by id, not as a copy: after a refresh the drawer reads the current item, and says so if it is gone. */
type Selected = { kind: "alert"; id: string } | { kind: "request"; id: string } | null;

export default function NotificationsPage() {
  return (
    <DashboardShell {...PAGE_COPY["notifications"]}>
      <Notifications />
    </DashboardShell>
  );
}

type Row =
  | { kind: "alert"; at: string; key: string; alert: Layer1Alert }
  | { kind: "request"; at: string; key: string; request: DataRequestItem };

function Notifications() {
  const { notifications: n } = useShell();
  const [tab, setTab] = useHashTab(TABS.map((t) => t.id), "all");
  const [selected, setSelected] = useState<Selected>(null);

  const openRequests = n.dataRequests.filter(isOpenRequest);
  const alertRows: Row[] = n.alerts.map((a) => ({ kind: "alert", at: a.createdAt, key: `a-${a.priceEventId}`, alert: a }));
  const requestRows: Row[] = openRequests.map((r) => ({ kind: "request", at: r.createdAt, key: `r-${r.id}`, request: r }));
  const all = [...alertRows, ...requestRows].sort((x, y) => (x.at < y.at ? 1 : -1));

  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const refreshing = !loading && Boolean(n.refreshing);
  const alertsFailed = n.alertsStatus === "error";
  const requestsFailed = n.dataRequestsStatus === "error";
  const alertsHidden = n.alertsStatus === "forbidden";

  /** `sources` are the feeds this tab depends on. A list that is empty because a feed could not be read (or is hidden from this role) is NOT "all caught up". */
  const list = (rows: Row[], sources: ("alerts" | "requests")[], emptyTitle: string, emptyBody: string) => {
    if (loading) return <LoadingState lines={4} label="Loading notifications" />;
    const failed = sources.some((x) => (x === "alerts" ? alertsFailed : requestsFailed));
    const hidden = sources.length === 1 && sources[0] === "alerts" && alertsHidden;
    const hasAlerts = n.alerts.length > 0;
    const hasRequests = openRequests.length > 0;
    return (
      <div className="flex flex-col gap-3" aria-busy={refreshing}>
        {n.alertsError && <ErrorNotice message={`Competitor alerts: ${n.alertsError}${hasAlerts ? " Showing the last alerts that loaded." : ""}`} onRetry={n.reload} />}
        {n.dataRequestsError && <ErrorNotice message={`Data requests: ${n.dataRequestsError}${hasRequests ? " Showing the last requests that loaded." : ""}`} onRetry={n.reload} />}
        {alertsHidden && (
          <p className="t-meta" style={{ color: "var(--text-6)" }}>
            Competitor alerts are hidden: your role does not have access to Competitor Intelligence.
          </p>
        )}
        {rows.length === 0 ? (
          failed ? (
            <p className="t-body-sm" style={{ color: "var(--text-5)" }}>
              This is not an all-clear: the list could not be loaded, so Metrion cannot say whether anything needs you.
            </p>
          ) : hidden ? null : (
            <div className="mt-panel">
              <EmptyState icon="check" title={emptyTitle} description={emptyBody} />
            </div>
          )
        ) : (
          <ul className="m-0 flex list-none flex-col p-0 transition-opacity" style={{ opacity: refreshing ? 0.7 : 1 }}>
            {rows.map((r) => (
              <li key={r.key}>
                <NotificationItem
                  row={r}
                  onOpen={() => setSelected(r.kind === "alert" ? { kind: "alert", id: r.alert.priceEventId } : { kind: "request", id: r.request.id })}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  };

  // The drawer reads the CURRENT item for what is selected, so a refresh can never leave an outdated copy on screen as if it were current.
  const selAlert = selected?.kind === "alert" ? n.alerts.find((a) => a.priceEventId === selected.id) : undefined;
  const selRequest = selected?.kind === "request" ? openRequests.find((r) => r.id === selected.id) : undefined;
  const gone = selected !== null && !selAlert && !selRequest;

  return (
    <div className="mt-content flex flex-col gap-6">
      <Tabs
        tabs={TABS.map((t) => ({
          ...t,
          count: t.id === "alerts" ? alertRows.length : t.id === "requests" ? requestRows.length : all.length,
        }))}
        active={tab}
        onChange={setTab}
        label="Notification types"
        idPrefix="notif"
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="notif-context">
        <p role="status" className="m-0 t-meta" style={{ color: "var(--text-5)" }}>
          {loading ? "Loading…" : refreshing ? "Refreshing… what is shown is the last list that loaded." : n.checkedAt ? `${all.length} ${all.length === 1 ? "item" : "items"} · checked ${n.checkedAt}` : "Not checked yet."}
        </p>
        <button type="button" onClick={n.reload} disabled={loading || refreshing} className="mt-btn mt-btn-secondary mt-focus inline-flex min-h-[40px] items-center gap-2 rounded-lg px-3 py-1 t-meta font-bold disabled:cursor-not-allowed" style={{ opacity: loading || refreshing ? 0.7 : 1 }}>
          {refreshing && <Spinner size={12} />}
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <p className="t-body" style={{ color: "var(--text-5)" }}>
        Competitor alerts from the last {ALERT_WINDOW_DAYS} days and data requests still open. There is no read or unread state, so nothing here can be marked as read.
      </p>
      <TabPanel id="all" active={tab} idPrefix="notif">
        {list(all, ["alerts", "requests"], alertsHidden ? "No open data requests" : "You're all caught up", alertsHidden ? "The CFO is not waiting on any input from you. Competitor alerts are not shown for your role." : "No competitor alerts and no open data requests right now.")}
      </TabPanel>
      <TabPanel id="alerts" active={tab} idPrefix="notif">
        {list(alertRows, ["alerts"], "No competitor alerts", `No price or availability alerts in the last ${ALERT_WINDOW_DAYS} days.`)}
      </TabPanel>
      <TabPanel id="requests" active={tab} idPrefix="notif">
        {list(requestRows, ["requests"], "No open data requests", "The CFO is not waiting on any input from you.")}
      </TabPanel>

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selAlert ? selAlert.competitorLabel : selected?.kind === "request" ? "Data request" : selected ? "Competitor alert" : ""}
        subtitle={selected?.kind === "alert" ? "Competitor alert" : "Needs your input"}
        status={
          selAlert ? (
            <StatusBadge tone="neutral" dot>
              {selAlert.thresholdBreached ? "Crossed alert threshold" : "Informational"}
            </StatusBadge>
          ) : selRequest ? (
            <StatusBadge tone="warning" dot>
              {requestStatusLabel(selRequest.status)}
            </StatusBadge>
          ) : undefined
        }
      >
        {selAlert && <AlertDetail alert={selAlert} />}
        {selRequest && <RequestDetail request={selRequest} />}
        {gone && (
          <p role="status" className="t-body" style={{ color: "var(--text-4)" }}>
            {selected?.kind === "alert" ? `This alert is no longer in the last ${ALERT_WINDOW_DAYS} days of alerts.` : "This request is no longer open: it may have been answered."} The list has been updated.
          </p>
        )}
      </DetailDrawer>
    </div>
  );
}

/** `OPEN` is the one status the backend contract establishes for a data request; anything else is shown exactly as returned, never mapped to a guessed meaning. */
function requestStatusLabel(status: string): string {
  return status.toUpperCase() === "OPEN" ? "Open" : status;
}

function NotificationItem({ row, onOpen }: { row: Row; onOpen: () => void }) {
  const isAlert = row.kind === "alert";
  return (
    <button
      type="button"
      onClick={onOpen}
      className="mt-row mt-focus flex w-full items-start gap-4 rounded-lg px-2 py-4 text-left"
      style={{ borderBottom: "1px solid var(--border-subtle)" }}
    >
      <span className="mt-0.5 w-[112px] flex-shrink-0">
        <StatusBadge tone={isAlert ? "info" : "warning"}>{isAlert ? "Competitor" : "CFO needs input"}</StatusBadge>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block t-body-lg font-semibold" style={{ color: "var(--text-2)" }}>
          {isAlert ? row.alert.message : row.request.requestedField}
        </span>
        {!isAlert && row.request.reason && (
          <span className="mt-0.5 block t-meta" style={{ color: "var(--text-6)" }}>
            {row.request.reason}
          </span>
        )}
        <time className="mt-1 block t-meta-sm" style={{ color: "var(--text-6)" }} dateTime={row.at}>
          {new Date(row.at).toLocaleString()}
        </time>
      </span>
      <span className="mt-1 inline-flex flex-shrink-0" style={{ color: "var(--text-6)", transform: "rotate(-90deg)" }} aria-hidden>
        <Icon name="chevron" size={16} />
      </span>
    </button>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="t-micro font-bold uppercase tracking-wider" style={{ color: "var(--text-6)" }}>
        {label}
      </div>
      <div className="mt-1 t-body" style={{ color: "var(--text-3)" }}>
        {children}
      </div>
    </div>
  );
}

function AlertDetail({ alert }: { alert: Layer1Alert }) {
  const h = alert.handoff;
  return (
    <div className="flex flex-col gap-4">
      <Fact label="What happened">{alert.message}</Fact>
      {h.validatedFact.length > 0 && (
        <Fact label="Evidence">
          <ul className="m-0 flex list-none flex-col p-0">
            {h.validatedFact.map((f, i) => {
              const state = evidenceStateForTier(f.confidence);
              return (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span>{f.fact}</span>
                  {state && <EvidenceStateBadge state={state} />}
                  {f.isStale && <StatusBadge tone="warning">Stale</StatusBadge>}
                </li>
              );
            })}
          </ul>
        </Fact>
      )}
      <Fact label="Why it matters">{h.implication}</Fact>
      {h.suggestedAction && <Fact label="Suggested next question">{h.suggestedAction.suggestedQuestion}</Fact>}
      <Link
        href="/dashboard/competitors"
        className="mt-btn mt-focus inline-flex w-fit items-center rounded-lg px-3 py-2 t-body-sm font-bold"
        style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
      >
        Open Competitors
      </Link>
      <p className="t-meta-sm" style={{ color: "var(--text-6)" }}>
        Metrion only recommends. It never changes a price or a listing on a marketplace.
      </p>
    </div>
  );
}

function RequestDetail({ request }: { request: DataRequestItem }) {
  return (
    <div className="flex flex-col gap-4">
      <Fact label="Needed">{request.requestedField}</Fact>
      <Fact label="Why">{request.reason ?? "No reason was recorded."}</Fact>
      {request.blockingMetric && <Fact label="Blocking this figure">{request.blockingMetric}</Fact>}
      <Fact label="Status">{requestStatusLabel(request.status)}</Fact>
      <Link
        href="/dashboard/cfo#anomalies"
        className="mt-btn mt-focus inline-flex w-fit items-center rounded-lg px-3 py-2 t-body-sm font-bold"
        style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
      >
        Open in CFO
      </Link>
    </div>
  );
}
