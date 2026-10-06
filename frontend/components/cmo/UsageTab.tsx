"use client";

import { EmptyState } from "@/components/ui/EmptyState";
import { Section } from "@/components/ui/Section";
import { useCmoSession } from "@/components/cmo/session";

/** What this browser session has used. The server is the record of truth for plan limits and monthly totals; there is no CMO usage
 * endpoint yet, so this page says exactly that instead of showing numbers it does not have. */
export function UsageTab() {
  const { ledger } = useCmoSession();
  const total = ledger.reduce((n, e) => n + e.units, 0);
  const shared = ledger.reduce((n, e) => n + (e.sharedUnits ?? 0), 0);
  return (
    <div className="mt-stack">
      <Section title="This session" hint="Units used since you opened this page. Approving a title, confirming a photo fact and managing niche terms are always free.">
        {ledger.length === 0 ? (
          <EmptyState compact icon="reports" title="Nothing used yet" description="Anything you write or research will be listed here with its cost." />
        ) : (
          <>
            <div className="mb-3 t-body" style={{ color: "var(--text-2)" }}>
              {total} marketing unit{total === 1 ? "" : "s"}{shared > 0 ? ` and ${shared} market-research unit${shared === 1 ? "" : "s"}` : ""} used this session.
            </div>
            <div className="mt-table-wrap">
              <table className="mt-table">
                <caption className="sr-only">Units used in this session</caption>
                <thead><tr><th scope="col">When</th><th scope="col">What</th><th scope="col">Units</th></tr></thead>
                <tbody>
                  {ledger.map((e, i) => (
                    <tr key={`${e.at}-${i}`}>
                      <td>{new Date(e.at).toLocaleTimeString()}</td>
                      <td>{e.action}</td>
                      <td>{e.units}{e.sharedUnits ? ` + ${e.sharedUnits} research` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>
      <p className="t-meta" style={{ color: "var(--text-6)" }}>
        Your plan’s monthly limits and totals are enforced by the server. A usage view with those totals is not available yet, so none are shown here.
      </p>
    </div>
  );
}
