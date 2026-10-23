"use client";

import { PAGE_COPY } from "@/lib/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { isOpenRequest } from "@/lib/useNotifications";
import { useHashTab } from "@/lib/useHashTab";
import { apiFetch, type DataRequestItem, type UploadOutcome } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { PeriodPnlSection } from "@/components/cfo/sections/PeriodPnlSection";
import { GstLineAnalysisSection, GstPeriodSummarySection, GstLookupSection } from "@/components/cfo/sections/GstSections";
import { PricingCurveSection, LandedCostSection, SupplierRankingSection, BatchSizeSection, FundingReadinessSection } from "@/components/cfo/sections/PricingSections";
import { ReconcileSection, CashReconciliationSection, CfoPreviewSection, AnomalyCheckSection, PeriodComparisonSection, DataRequestsSection } from "@/components/cfo/sections/ReportingSections";
import { DataImportsTab } from "@/components/cfo/v2/data/DataImportsTab";
import { CashTaxTab } from "@/components/cfo/v2/cash/CashTaxTab";
import { ExpensesTab } from "@/components/cfo/v2/expenses/ExpensesTab";
import { IntelligenceTab } from "@/components/cfo/v2/intelligence/IntelligenceTab";
import { LeakShieldTab } from "@/components/cfo/v2/leak/LeakShieldTab";
import { OverviewTab } from "@/components/cfo/v2/overview/OverviewTab";
import { ProfitabilityTab } from "@/components/cfo/v2/profitability/ProfitabilityTab";
import { useDefaultPeriod } from "@/lib/cfoV2/useDefaultPeriod";
import { IngestUploadSection, SellerGoalSection, FinancialHealthSection, StrategicBriefingSection } from "@/components/cfo/sections/ImportAndGoalSections";

const CFO_TABS = [
  { id: "overview", label: "Overview" },
  { id: "profitability", label: "Profitability" },
  { id: "expenses", label: "Expenses" },
  { id: "leak", label: "Leak Shield" },
  { id: "cash", label: "Cash & Tax" },
  { id: "intelligence", label: "Intelligence" },
  { id: "data", label: "Data & imports" },
  { id: "tools", label: "Tools" },
] as const;

const CFO_TAB_BLURBS: Record<(typeof CFO_TABS)[number]["id"], string> = {
  overview: "Your key figures, each with where it came from, how complete it is and what is missing.",
  profitability: "Contribution Profit by marketplace and SKU, the monthly trend, and what moved it between two periods.",
  expenses: "Your expense ledger and the Expense Tracker. Metrion suggests what kind of expense each is; nothing counts until you confirm it.",
  leak: "Discrepancies found between your orders and your settlements, ordered by how soon the claim window closes. Status is what you report.",
  cash: "Expected settlements and what you owe (an estimate, not a bank balance), GST status, and the pack for your CA.",
  intelligence: "Recommended actions and alerts from the checks Metrion runs on your data.",
  data: "Upload sales, settlement, advertising and expense files, follow each upload, and decide what to do with rows that were held back.",
  tools: "The direct tools: period P&L, price curves, landed cost, suppliers, reconciliation, GST lookups, anomaly checks and the original import. Informational — not tax advice.",
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
  const period = useDefaultPeriod();

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
  const tabs = CFO_TABS.map((t) => ({ ...t, count: t.id === "tools" ? openRequests : null }));

  return (
    <div className="mt-content flex flex-col gap-7">
      <div className="flex flex-col gap-3">
        <Tabs tabs={tabs} active={tab} onChange={setTab} label="CFO workspace" idPrefix="cfo" />
        <Link href="/dashboard/cfo/expenses" className="t-body-sm font-semibold mt-focus w-fit" style={{ color: "var(--accent)" }}>
          Open the Expense Tracker →
        </Link>
        <p className="t-body" style={{ color: "var(--text-5)" }}>
          {CFO_TAB_BLURBS[tab as (typeof CFO_TABS)[number]["id"]]}
        </p>
      </div>

      <TabPanel id="overview" active={tab} idPrefix="cfo">
        {period && <OverviewTab period={period} />}
      </TabPanel>
      <TabPanel id="profitability" active={tab} idPrefix="cfo">
        {period && <ProfitabilityTab period={period} />}
      </TabPanel>
      <TabPanel id="expenses" active={tab} idPrefix="cfo">
        {period && <ExpensesTab period={period} getToken={getToken} />}
      </TabPanel>
      <TabPanel id="leak" active={tab} idPrefix="cfo">
        <LeakShieldTab />
      </TabPanel>
      <TabPanel id="cash" active={tab} idPrefix="cfo">
        {period && <CashTaxTab period={period} />}
      </TabPanel>
      <TabPanel id="intelligence" active={tab} idPrefix="cfo">
        {period && <IntelligenceTab period={period} />}
      </TabPanel>
      <TabPanel id="data" active={tab} idPrefix="cfo">
        <DataImportsTab getToken={getToken} />
      </TabPanel>
      <TabPanel id="tools" active={tab} idPrefix="cfo">
        <div className="mt-stack">
          <div className="grid grid-cols-1 items-start gap-x-10 gap-y-9 xl:grid-cols-2">
            <FinancialHealthSection getToken={getToken} />
            <StrategicBriefingSection getToken={getToken} />
            <CfoPreviewSection getToken={getToken} />
            <SellerGoalSection getToken={getToken} />
          </div>
          <PeriodPnlSection getToken={getToken} />
          <PeriodComparisonSection getToken={getToken} />
          <PricingCurveSection getToken={getToken} />
          <LandedCostSection getToken={getToken} />
          <SupplierRankingSection getToken={getToken} />
          <BatchSizeSection getToken={getToken} />
          <ReconcileSection getToken={getToken} />
          <CashReconciliationSection getToken={getToken} />
          <FundingReadinessSection getToken={getToken} />
          <GstLineAnalysisSection getToken={getToken} />
          <GstPeriodSummarySection getToken={getToken} />
          <GstLookupSection getToken={getToken} />
          <DataRequestsSection rows={dataRequests} error={dataRequestsError} onReload={reloadDataRequests} />
          <AnomalyCheckSection getToken={getToken} />
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
