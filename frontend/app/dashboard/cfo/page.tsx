"use client";

import { PAGE_COPY } from "@/lib/navigation";
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
import { DataImportsTab } from "@/components/cfo/v2/data/DataImportsTab";
import { IngestUploadSection, SellerGoalSection, FinancialHealthSection, StrategicBriefingSection } from "@/components/cfo/sections/ImportAndGoalSections";

const CFO_TABS = [
  { id: "overview", label: "Overview" },
  { id: "profitability", label: "Profitability" },
  { id: "cash", label: "Cash & reconciliation" },
  { id: "gst", label: "GST" },
  { id: "anomalies", label: "Anomalies & requests" },
  { id: "import", label: "Import data" },
  { id: "data", label: "Data & imports" },
] as const;

const CFO_TAB_BLURBS: Record<(typeof CFO_TABS)[number]["id"], string> = {
  overview: "Financial health, the strategic briefing, a Leak Shield preview and the goal everything is measured against.",
  profitability: "True contribution profit, period comparison, price/margin curves, landed cost, suppliers and batch sizing.",
  cash: "Reconcile settlements to invoices, track expenses against a budget, and check funding readiness.",
  gst: "Line-level GST analysis, period summaries and HSN/rate lookup. Informational — not tax advice.",
  anomalies: "Statistical anomaly checks, and the inputs the CFO is asking you for.",
  import: "Upload marketplace reports. Metrion reads files you upload — it never connects to a marketplace account.",
  data: "Upload sales, settlement, advertising and expense files, follow each upload live, and read what happened to every row.",
};

/** The CFO workspace. Each tab groups the existing, real direct-execution tools
 * (`backend/src/backend/api/v1/cfo.py`) by the question they answer — nothing here computes or
 * invents a figure: every section calls a real route and renders exactly what comes back,
 * including genuine UNAVAILABLE / error / empty states. Money is entered/rendered in rupees and
 * converted to/from paise at the edge only. */
export default function CfoPage() {
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
    <div className="mt-content flex flex-col gap-7">
      <div className="flex flex-col gap-3">
        <Tabs tabs={tabs} active={tab} onChange={setTab} label="CFO workspace" idPrefix="cfo" />
        <p className="t-body" style={{ color: "var(--text-5)" }}>
          {CFO_TAB_BLURBS[tab as (typeof CFO_TABS)[number]["id"]]}
        </p>
      </div>

      <TabPanel id="overview" active={tab} idPrefix="cfo">
        <div className="grid grid-cols-1 items-start gap-x-10 gap-y-9 xl:grid-cols-2">
          <FinancialHealthSection getToken={getToken} />
          <StrategicBriefingSection getToken={getToken} />
          <CfoPreviewSection getToken={getToken} />
          <SellerGoalSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="profitability" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <PeriodPnlSection getToken={getToken} />
          <PeriodComparisonSection getToken={getToken} />
          <PricingCurveSection getToken={getToken} />
          <LandedCostSection getToken={getToken} />
          <SupplierRankingSection getToken={getToken} />
          <BatchSizeSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="cash" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <ReconcileSection getToken={getToken} />
          <CashReconciliationSection getToken={getToken} />
          <ExpenseTrackerSection getToken={getToken} />
          <FundingReadinessSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="gst" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <GstLineAnalysisSection getToken={getToken} />
          <GstPeriodSummarySection getToken={getToken} />
          <GstLookupSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="anomalies" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <DataRequestsSection rows={dataRequests} error={dataRequestsError} onReload={reloadDataRequests} />
          <AnomalyCheckSection getToken={getToken} />
        </div>
      </TabPanel>
      <TabPanel id="import" active={tab} idPrefix="cfo">
        <div className="mt-stack">
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
      <TabPanel id="data" active={tab} idPrefix="cfo">
        <DataImportsTab getToken={getToken} />
      </TabPanel>
    </div>
  );
}
