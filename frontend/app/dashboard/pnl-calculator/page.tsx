"use client";

import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { PnlWorkspace } from "@/components/pnl/PnlWorkspace";
import "@/components/overview/overview.css";
import "@/components/cfo/cfo-skin.css";
import { PAGE_COPY } from "@/lib/navigation";

/** The in-app Profit Calculator (docs/specs/calculator.md §14). A dashboard capability, not an agent: it collects typed numbers and shows the Brain 1
 * estimate returned by `POST /api/v1/cfo/pnl-scenario`. It sits inside the signed-in dashboard shell, so it needs a session and `agent.cfo`; the public,
 * no-login calculator is a separate deployment and is not part of this app. */
export default function PnlCalculatorPage() {
  return (
    <DashboardShell {...PAGE_COPY["pnl-calculator"]}>
      <div className="ov cfo-skin">
        <header className="ov-head ov-rise">
          <div>
            <h2 className="ov-h">What would you earn?</h2>
            <p className="ov-body" style={{ marginTop: 4 }}>Try a price with your own costs. An estimate, never saved.</p>
          </div>
        </header>
        <PnlWorkspace />
      </div>
    </DashboardShell>
  );
}
