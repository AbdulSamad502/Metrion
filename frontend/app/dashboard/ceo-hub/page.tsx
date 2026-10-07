"use client";

import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CeoHub } from "@/components/ceo/hub/CeoHubWorkspace";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

export default function CeoHubPage() {
  return (
    <DashboardShell title="CEO Hub" subtitle="The command centre: question, orchestration, findings, action">
      <div className="mt-content mt-stack">
        <CeoHub />
        <CompetitorIntelligence />
      </div>
    </DashboardShell>
  );
}

/** The Competitor Intelligence workspace — competitor tracking, Research Now / Again, snapshot history,
 * price & availability events, listing diff, price-positioning scenario, competitor-vs-product
 * comparison, seller products, discovery, market overview and digest. The same component also backs
 * `/dashboard/competitors`, so there is one implementation and every API call is unchanged. */
function CompetitorIntelligence() {
  return (
    <section id="competitor-intelligence" aria-labelledby="ceo-ci" className="scroll-mt-6">
      <h2 id="ceo-ci" className="mt-eyebrow">
        Competitor Intelligence
      </h2>
      <p className="mt-2 mb-5 t-body-sm" style={{ color: "var(--text-5)" }}>
        Direct-execution tools you can run yourself. Everything here runs against your own evidence and tracked competitors.
      </p>
      <CompetitorWorkspace />
    </section>
  );
}
