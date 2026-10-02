"use client";

import Link from "next/link";
import { useState } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { EvidenceStateBadge, evidenceStateForTier } from "@/components/ui/EvidenceStateBadge";
import { LoadingState } from "@/components/ui/LoadingState";
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

type Selected = { kind: "alert"; alert: Layer1Alert } | { kind: "request"; request: DataRequestItem } | null;

export default function NotificationsPage() {
  return (
    <DashboardShell title="Notifications" subtitle="Competitor alerts and inputs the CFO is waiting on">
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

  const list = (rows: Row[], emptyTitle: string, emptyBody: string) => {
    if (loading) return <LoadingState lines={4} label="Loading notifications" />;
    return (
      <div className="flex flex-col gap-3">
        {n.alertsError && <ErrorNotice message={`Competitor alerts: ${n.alertsError}`} onRetry={n.reload} />}
        {n.dataRequestsError && <ErrorNotice message={`Data requests: ${n.dataRequestsError}`} onRetry={n.reload} />}
        {n.alertsStatus === "forbidden" && (
          <p className="t-meta" style={{ color: "var(--text-6)" }}>
            Competitor alerts are hidden: your role does not have access to Competitor Intelligence.
          </p>
        )}
        {rows.length === 0 ? (
          <div className="mt-panel">
            <EmptyState icon="check" title={emptyTitle} description={emptyBody} />
          </div>
        ) : (
          <ul className="m-0 flex list-none flex-col p-0">
            {rows.map((r) => (
              <li key={r.key}>
                <NotificationItem
                  row={r}
                  onOpen={() => setSelected(r.kind === "alert" ? { kind: "alert", alert: r.alert } : { kind: "request", request: r.request })}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  };

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
      <p className="t-body" style={{ color: "var(--text-5)" }}>
        Shows competitor alerts from the last {ALERT_WINDOW_DAYS} days and data requests that are still open. Metrion does not
        track read or unread yet, so nothing here can be marked as read.
      </p>
      <TabPanel id="all" active={tab} idPrefix="notif">
        {list(all, "You're all caught up", "No competitor alerts and no open data requests right now.")}
      </TabPanel>
      <TabPanel id="alerts" active={tab} idPrefix="notif">
        {list(alertRows, "No competitor alerts", `No price or availability alerts in the last ${ALERT_WINDOW_DAYS} days.`)}
      </TabPanel>
      <TabPanel id="requests" active={tab} idPrefix="notif">
        {list(requestRows, "No open data requests", "The CFO is not waiting on any input from you.")}
      </TabPanel>

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.kind === "alert" ? selected.alert.competitorLabel : "Data request"}
        subtitle={selected?.kind === "alert" ? "Competitor alert" : "Needs your input"}
        status={
          selected?.kind === "alert" ? (
            <StatusBadge tone={selected.alert.thresholdBreached ? "negative" : "info"} dot>
              {selected.alert.thresholdBreached ? "Alert-worthy" : "Informational"}
            </StatusBadge>
          ) : selected?.kind === "request" ? (
            <StatusBadge tone="warning" dot>
              {selected.request.status.toLowerCase()}
            </StatusBadge>
          ) : undefined
        }
      >
        {selected?.kind === "alert" && <AlertDetail alert={selected.alert} />}
        {selected?.kind === "request" && <RequestDetail request={selected.request} />}
      </DetailDrawer>
    </div>
  );
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
        <time className="mt-1 block t-meta-sm" style={{ color: "var(--text-7)" }} dateTime={row.at}>
          {new Date(row.at).toLocaleString()}
        </time>
      </span>
      <span className="mt-1 flex-shrink-0" style={{ color: "var(--text-6)" }}>
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
      <Fact label="Status">{request.status.toLowerCase()}</Fact>
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
