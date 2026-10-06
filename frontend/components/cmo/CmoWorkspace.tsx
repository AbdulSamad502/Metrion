"use client";

import { PipelineStepper, type FlowStep } from "@/components/ci/EvidenceTrail";
import { CatalogTab } from "@/components/cmo/CatalogTab";
import { CopyTab } from "@/components/cmo/CopyTab";
import { CreateTab } from "@/components/cmo/CreateTab";
import { NicheTab } from "@/components/cmo/NicheTab";
import { CmoSessionProvider, useCmoSession } from "@/components/cmo/session";
import { StandaloneTab } from "@/components/cmo/StandaloneTab";
import { TitlesTab } from "@/components/cmo/TitlesTab";
import { TrendsTab } from "@/components/cmo/TrendsTab";
import { UsageTab } from "@/components/cmo/UsageTab";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { useHashTab } from "@/lib/useHashTab";

const CMO_TABS = [
  { id: "product", label: "Product" },
  { id: "titles", label: "Titles" },
  { id: "copy", label: "Listing copy" },
  { id: "standalone", label: "One piece & hashtags" },
  { id: "catalog", label: "Catalog Q&A" },
  { id: "niche", label: "Niche" },
  { id: "trends", label: "Market trends" },
  { id: "usage", label: "Usage" },
] as const;

const CMO_STEPS: FlowStep[] = [
  { name: "Product", detail: "Photo (optional), details and marketplaces." },
  { name: "Titles", detail: "Options per marketplace; you choose and approve." },
  { name: "Listing copy", detail: "Description, bullets and keywords from your approved title." },
  { name: "Catalog Q&A", detail: "Every answer says where it came from." },
  { name: "Market trends", detail: "Research on your confirmed niche, with sources and dates." },
];

/** Slim CMO workspace. Recommend-only: it produces text for you to copy; it never publishes to a marketplace. Every number of
 * units shown is what the server reported; nothing on this page is sample data. */
export function CmoWorkspace() {
  return (
    <CmoSessionProvider>
      <Inner />
    </CmoSessionProvider>
  );
}

function Inner() {
  const [tab, setTab] = useHashTab(CMO_TABS.map((t) => t.id), "product");
  const { approvals } = useCmoSession();
  return (
    <div className="mt-content flex flex-col gap-7">
      <PipelineStepper steps={CMO_STEPS} label="Marketing workflow" />
      <Tabs tabs={CMO_TABS.map((t) => ({ ...t, count: t.id === "titles" ? Object.keys(approvals).length : null }))} active={tab} onChange={setTab} label="Marketing workspace" idPrefix="cmo" />
      <TabPanel id="product" active={tab} idPrefix="cmo"><CreateTab onNext={() => setTab("titles")} /></TabPanel>
      <TabPanel id="titles" active={tab} idPrefix="cmo"><TitlesTab onNext={() => setTab("copy")} /></TabPanel>
      <TabPanel id="copy" active={tab} idPrefix="cmo"><CopyTab /></TabPanel>
      <TabPanel id="standalone" active={tab} idPrefix="cmo"><StandaloneTab /></TabPanel>
      <TabPanel id="catalog" active={tab} idPrefix="cmo"><CatalogTab /></TabPanel>
      <TabPanel id="niche" active={tab} idPrefix="cmo"><NicheTab /></TabPanel>
      <TabPanel id="trends" active={tab} idPrefix="cmo"><TrendsTab /></TabPanel>
      <TabPanel id="usage" active={tab} idPrefix="cmo"><UsageTab /></TabPanel>
    </div>
  );
}
