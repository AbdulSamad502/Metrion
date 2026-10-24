"use client";

import Link from "next/link";
import { PAGE_COPY } from "@/lib/navigation";
import "@/components/overview/overview.css";
import "@/components/cfo/cfo-skin.css";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { isOpenRequest } from "@/lib/useNotifications";
import { useHashTab } from "@/lib/useHashTab";
import { apiFetch, type DataRequestItem, type UploadOutcome } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { ExpenseTrackerSection } from "@/components/cfo/sections/ExpenseTrackerSection";
import { PeriodPnlSection } from "@/components/cfo/sections/PeriodPnlSection";
import { GstLineAnalysisSection, GstPeriodSummarySection, GstLookupSection } from "@/components/cfo/sections/GstSections";
import { PricingCurveSection, LandedCostSection, SupplierRankingSection, BatchSizeSection, FundingReadinessSection } from "@/components/cfo/sections/PricingSections";
import { ReconcileSection, CashReconciliationSection, CfoPreviewSection, AnomalyCheckSection, PeriodComparisonSection, DataRequestsSection } from "@/components/cfo/sections/ReportingSections";
import { IngestUploadSection, SellerGoalSection, FinancialHealthSection, StrategicBriefingSection } from "@/components/cfo/sections/ImportAndGoalSections";

const CFO_TABS = [
  { id: "overview", label: "Overview" },
  { id: "profitability", label: "Profitability" },
  { id: "cash", label: "Cash & reconciliation" },
  { id: "gst", label: "GST" },
  { id: "anomalies", label: "Anomalies & requests" },
  { id: "import", label: "Import data" },
] as const;

const CFO_TAB_BLURBS: Record<(typeof CFO_TABS)[number]["id"], string> = {
  overview: "Rate your financial health, build a strategic briefing, try a free Leak Shield preview and note your goal. The goal only gives background to the written summary.",
  profitability: "Contribution profit for a period, how two results compare, margin at different prices, landed cost, supplier quotes and batch size.",
  cash: "Check settlements against invoices, run a cash reconciliation, track expenses against a budget and check funding readiness.",
  gst: "GST by line, GST for a period and a rate lookup. Informational only, not tax advice.",
  anomalies: "Check for unusual changes, and answer what Metrion needs from you.",
  import: "Upload marketplace reports. Metrion reads files you upload — it never connects to a marketplace account.",
};

/** The CFO workspace. Each tab groups the existing, real direct-execution tools
 * (`backend/src/backend/api/v1/cfo.py`) by the question they answer — nothing here computes or
 * invents a figure: every section calls a real route and renders exactly what comes back,
 * including genuine UNAVAILABLE / error / empty states. Money is entered/rendered in rupees and
 * converted to/from paise at the edge only. */
export default function CfoToolsPage() {
  return (
    <DashboardShell {...PAGE_COPY["cfo"]}>
      <CfoWorkspace />
    </DashboardShell>
  );
}

function CfoWorkspace() {
  const { getToken } = useAuth();
  const [tab, setTab] = useHashTab(CFO_TABS.map((t) => t.id), "overview");

  // The latest upload and a bump counter, so Import history refreshes and can surface a duplicate.
  const [lastUpload, setLastUpload] = useState<UploadOutcome | null>(null);
  const [importsTick, setImportsTick] = useState(0);

  const [dataRequests, setDataRequests] = useState<DataRequestItem[] | null>(null);
  const [dataRequestsError, setDataRequestsError] = useState<string | null>(null);

  const reloadDataRequests = async () => {
    try {
      const token = await getToken();
      const rows = await apiFetch<DataRequestItem[]>("/api/v1/cfo/data-requests", token);
      setDataRequests(rows);
    } catch (e) {
      setDataRequestsError(friendlyApiError(e, "Could not reach the backend"));
    }
  };

  useEffect(() => {
    (async () => {
      await reloadDataRequests();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openRequests = (dataRequests ?? []).filter(isOpenRequest).length;
  const tabs = CFO_TABS.map((t) => ({ ...t, count: t.id === "anomalies" ? openRequests : null }));

  return (
    <div className="ov cfo-skin mt-content">
      <Link href="/dashboard/cfo" className="ov-btn ov-btn--ghost min-h-10" style={{ width: "fit-content" }}>← Back to Profit &amp; Finance</Link>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Tabs tabs={tabs} active={tab} onChange={setTab} label="CFO workspace" idPrefix="cfo" />
        <p className="ov-body">
          {CFO_TAB_BLURBS[tab as (typeof CFO_TABS)[number]["id"]]}
        </p>
      </div>

      <TabPanel id="overview" active={tab} idPrefix="cfo">
        <div className="cfo-grid">
          <FinancialHealthSection getToken={getToken} />
          <StrategicBriefingSection getToken={getToken} />
          <CfoPreviewSection getToken={getToken} />
          <SellerGoalSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="profitability" active={tab} idPrefix="cfo">
        <div className="mt-stack cfo-stack">
          <PeriodPnlSection getToken={getToken} />
          <PeriodComparisonSection getToken={getToken} />
          <PricingCurveSection getToken={getToken} />
          <LandedCostSection getToken={getToken} />
          <SupplierRankingSection getToken={getToken} />
          <BatchSizeSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="cash" active={tab} idPrefix="cfo">
        <div className="mt-stack cfo-stack">
          <ReconcileSection getToken={getToken} />
          <CashReconciliationSection getToken={getToken} />
          <ExpenseTrackerSection getToken={getToken} />
          <FundingReadinessSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="gst" active={tab} idPrefix="cfo">
        <div className="mt-stack cfo-stack">
          <GstLineAnalysisSection getToken={getToken} />
          <GstPeriodSummarySection getToken={getToken} />
          <GstLookupSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="anomalies" active={tab} idPrefix="cfo">
        <div className="mt-stack cfo-stack">
          <DataRequestsSection rows={dataRequests} error={dataRequestsError} onReload={reloadDataRequests} />
          <AnomalyCheckSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="import" active={tab} idPrefix="cfo">
        <div className="mt-stack cfo-stack">
          <IngestUploadSection
            getToken={getToken}
            onUploaded={(outcome) => {
              setLastUpload(outcome);
              setImportsTick((n) => n + 1);
            }}
          />
          <ImportHistory getToken={getToken} refreshTick={importsTick} lastUpload={lastUpload} />
        </div>
      </TabPanel>
    </div>
  );
}
