"use client";

import { PAGE_COPY } from "@/lib/navigation";
import Link from "next/link";
import { useState } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { Icon } from "@/components/ui/Icon";
import { ErrorBanner, LoadingLines, Pill, RefreshButton } from "@/components/overview/parts";
import "@/components/overview/overview.css";
import { EvidenceStateBadge, evidenceStateForTier } from "@/components/ui/EvidenceStateBadge";
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
    if (loading) return <LoadingLines lines={4} label="Loading notifications" />;
    const failed = sources.some((x) => (x === "alerts" ? alertsFailed : requestsFailed));
    const hidden = sources.length === 1 && sources[0] === "alerts" && alertsHidden;
    const hasAlerts = n.alerts.length > 0;
    const hasRequests = openRequests.length > 0;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }} aria-busy={refreshing}>
        {n.alertsError && <ErrorBanner message={`Competitor alerts: ${n.alertsError}${hasAlerts ? " Showing the last alerts that loaded." : ""}`} onRetry={n.reload} />}
        {n.dataRequestsError && <ErrorBanner message={`Data requests: ${n.dataRequestsError}${hasRequests ? " Showing the last requests that loaded." : ""}`} onRetry={n.reload} />}
        {alertsHidden && (
          <p className="ov-meta">
            Alerts are hidden for your role.
          </p>
        )}
        {rows.length === 0 ? (
          failed ? (
            <p className="ov-note" role="status">
              This isn’t an all-clear: the list didn’t load.
            </p>
          ) : hidden ? null : (
            <div className="ov-card">
              <div className="ov-empty">
                <span className="ov-badge-circle ov-badge-circle--good"><Icon name="check" size={24} /></span>
                <div>
                  <h3 className="ov-h">{emptyTitle}</h3>
                  <p className="ov-body" style={{ marginTop: 8, maxWidth: "52ch" }}>{emptyBody}</p>
                </div>
              </div>
            </div>
          )
        ) : (
          <ul className="ov-card ov-rows" style={{ opacity: refreshing ? 0.7 : 1, transition: "opacity 200ms ease", gap: 0, padding: 16 }}>
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
    <div className="ov mt-content">
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
      <div className="ov-head-r" style={{ justifyContent: "space-between" }} data-testid="notif-context">
        <p role="status" className="ov-meta" style={{ margin: 0 }}>
          {loading ? "Loading…" : refreshing ? "Refreshing… what is shown is the last list that loaded." : n.checkedAt ? `${all.length} ${all.length === 1 ? "item" : "items"} · checked ${n.checkedAt}` : "Not checked yet."}
        </p>
        <RefreshButton spinning={refreshing} onClick={n.reload} />
      </div>
      <p className="ov-body">
        Last {ALERT_WINDOW_DAYS} days. Nothing is marked read.
      </p>
      <TabPanel id="all" active={tab} idPrefix="notif">
        {list(all, ["alerts", "requests"], alertsHidden ? "No open data requests" : "You're all caught up", alertsHidden ? "Nothing waiting on you. Alerts aren’t shown for your role." : "No alerts or open requests.")}
      </TabPanel>
      <TabPanel id="alerts" active={tab} idPrefix="notif">
        {list(alertRows, ["alerts"], "No competitor alerts", `None in the last ${ALERT_WINDOW_DAYS} days.`)}
      </TabPanel>
      <TabPanel id="requests" active={tab} idPrefix="notif">
        {list(requestRows, ["requests"], "No open data requests", "Nothing waiting on you.")}
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
          <p role="status" className="ov-body">
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
    <button type="button" onClick={onOpen} className="ov-row mt-focus" style={{ width: "100%", border: 0, background: "transparent", textAlign: "left", font: "inherit", cursor: "pointer", alignItems: "flex-start", padding: 16 }}>
      <span className={`ov-badge-circle ov-badge-circle--${isAlert ? "brand" : "warn"}`}><Icon name={isAlert ? "competitors" : "finance"} size={18} /></span>
      <span className="ov-row-main">
        <span className="ov-title" style={{ display: "block" }}>{isAlert ? row.alert.message : row.request.requestedField}</span>
        {!isAlert && row.request.reason && <span className="ov-meta">{row.request.reason}</span>}
        <time className="ov-meta" dateTime={row.at}>{new Date(row.at).toLocaleString()}</time>
      </span>
      <span className="ov-row-end"><Pill tone={isAlert ? "brand" : "warn"}>{isAlert ? "Competitor" : "CFO needs input"}</Pill><Icon name="arrow" size={14} strokeWidth={2} className="ov-arrow" /></span>
    </button>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="ov-meta">
        {label}
      </div>
      <div className="ov-body" style={{ marginTop: 4, color: "var(--ov-ink)" }}>
        {children}
      </div>
    </div>
  );
}

function AlertDetail({ alert }: { alert: Layer1Alert }) {
  const h = alert.handoff;
  return (
    <div className="ov" style={{ gap: 24, maxWidth: "none" }}>
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
        className="ov-btn ov-btn--brand min-h-10" style={{ width: "fit-content" }}
      >
        Open Competitors
      </Link>
      <p className="ov-meta">
        Metrion only recommends. It never changes a price or a listing on a marketplace.
      </p>
    </div>
  );
}

function RequestDetail({ request }: { request: DataRequestItem }) {
  return (
    <div className="ov" style={{ gap: 24, maxWidth: "none" }}>
      <Fact label="Needed">{request.requestedField}</Fact>
      <Fact label="Why">{request.reason ?? "No reason was recorded."}</Fact>
      {request.blockingMetric && <Fact label="Blocking this figure">{request.blockingMetric}</Fact>}
      <Fact label="Status">{requestStatusLabel(request.status)}</Fact>
      <Link
        href="/dashboard/cfo#requests"
        className="ov-btn ov-btn--brand min-h-10" style={{ width: "fit-content" }}
      >
        Open in CFO
      </Link>
    </div>
  );
}
