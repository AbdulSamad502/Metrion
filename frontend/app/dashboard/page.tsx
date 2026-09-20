"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { useAppSession } from "@/lib/useAppSession";
import { ApiError, apiFetch, type AgentStatus, type CiSummary } from "@/lib/api";

/** The post-auth landing screen (auth.md exit bar + the provided design reference).
 * Static for now, per scope: this proves a signed-in, onboarded user lands somewhere
 * real and reliable — the actual profit-intelligence data wiring is a later step. */
export default function DashboardPage() {
  const { session, error, displayName, roleLabel } = useAppSession();

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--negative)" }}>
        {error}
      </div>
    );
  }

  if (!session) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--text-5)" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="flex" style={{ background: "var(--bg-base)" }}>
      <Sidebar userName={displayName} roleLabel={roleLabel} active="Overview" />
      <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar title="Overview" subtitle="Profit, drivers, leaks and opportunities" />
        <div className="flex-1 overflow-y-auto px-8 py-7">
          <AgentStatusAndCiSummary />
          <div className="mt-4">
            <OverviewContent />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Step 4 — minimal, functional Agent Status + CI activity summary for the main dashboard.
 * Deliberately undecorated (no charts, no animation) per scope; navigation into the CEO
 * Hub / CI research flow lives here rather than a separate standalone page. */
function AgentStatusAndCiSummary() {
  const { getToken } = useAuth();
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [summary, setSummary] = useState<CiSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        const [a, s] = await Promise.all([
          apiFetch<AgentStatus[]>("/api/v1/ceo-hub/agents", token),
          apiFetch<CiSummary>("/api/v1/ci/summary", token),
        ]);
        setAgents(a);
        setSummary(s);
      } catch (e) {
        setLoadError(e instanceof ApiError ? e.message : "Could not reach the backend");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card style={{ padding: "16px 20px" }}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: "var(--text-6)" }}>
            Agents
          </span>
          {loadError ? (
            <span className="text-[12.5px]" style={{ color: "var(--negative)" }}>{loadError}</span>
          ) : !agents ? (
            <span className="text-[12.5px]" style={{ color: "var(--text-6)" }}>Loading…</span>
          ) : (
            agents.map((a) => (
              <span key={a.id} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px]" style={{ border: "1px solid var(--border-default)" }}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: a.status === "CONNECTED" ? "var(--accent)" : "var(--text-7)" }} />
                <span style={{ color: "var(--text-3)" }}>{a.name}</span>
              </span>
            ))
          )}
        </div>
        <Link href="/dashboard/ceo-hub" className="whitespace-nowrap text-[12.5px] font-bold" style={{ color: "var(--accent)" }}>
          Open CEO Hub →
        </Link>
      </div>
      {summary && (
        <div className="mt-3 flex flex-wrap gap-5 text-[12.5px]" style={{ color: "var(--text-4)" }}>
          <span>
            <strong style={{ color: "var(--text-2)" }}>{summary.trackedCompetitors}</strong> competitors tracked
          </span>
          <span>
            Last research:{" "}
            <strong style={{ color: "var(--text-2)" }}>
              {summary.lastResearchAt ? new Date(summary.lastResearchAt).toLocaleString() : "never"}
            </strong>
          </span>
          <span>
            <strong style={{ color: "var(--text-2)" }}>{summary.recentPriceEvents7d}</strong> price changes (7d)
          </span>
          {summary.pendingManualEntry > 0 && (
            <span style={{ color: "var(--negative)" }}>
              <strong>{summary.pendingManualEntry}</strong> competitor(s) need manual entry
            </span>
          )}
          {summary.staleCompetitors > 0 && (
            <span style={{ color: "var(--negative)" }}>
              <strong>{summary.staleCompetitors}</strong> competitor(s) stale (&gt;7 days)
            </span>
          )}
        </div>
      )}
    </Card>
  );
}

function Card({ children, className = "", style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`rounded-xl ${className}`}
      style={{
        background: "var(--bg-card)",
        backdropFilter: "blur(34px) saturate(190%)",
        border: "1px solid var(--border-default)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function OverviewContent() {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-[1.6fr_1fr] gap-3.5">
        <Card style={{ background: "var(--bg-card-elevated)", border: "1px solid var(--accent-border-default)", padding: "24px 26px" }}>
          <div className="flex items-center gap-2">
            <span className="text-[11.5px] font-bold uppercase tracking-wider" style={{ color: "var(--text-mint)" }}>
              Net Profit
            </span>
            <span className="rounded px-1.5 py-0.5 text-[9.5px] font-bold" style={{ background: "var(--border-subtle)", color: "var(--text-8)" }}>
              Measured
            </span>
          </div>
          <div className="mt-2 text-[42px] font-bold" style={{ color: "var(--text-hero)" }}>
            ₹6,24,000
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-2.5 text-[13.5px]">
            <span className="font-bold" style={{ color: "var(--accent)" }}>
              ↑ 15.3%
            </span>
            <span style={{ color: "var(--text-7)" }}>vs last month</span>
            <span style={{ color: "var(--divider-dot)" }}>·</span>
            <span style={{ color: "var(--text-4)" }}>Margin 28.4%</span>
            <span className="font-semibold" style={{ color: "var(--accent)" }}>
              (+2.6 pts)
            </span>
          </div>
        </Card>

        <Card style={{ padding: "18px 22px", display: "flex", flexDirection: "column", justifyContent: "center", gap: "14px" }}>
          <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-6)" }}>
            Revenue &amp; Spend
          </div>
          <div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs" style={{ color: "var(--text-4)" }}>
                Revenue
              </span>
              <span className="text-base font-bold" style={{ color: "var(--text-2)" }}>
                ₹24,85,430
              </span>
            </div>
            <div className="mt-0.5 text-[11.5px] font-semibold" style={{ color: "var(--accent)" }}>
              ↑ 10.6% vs last 7 days
            </div>
          </div>
          <div className="h-px" style={{ background: "var(--border-subtle)" }} />
          <div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs" style={{ color: "var(--text-4)" }}>
                Ad Spend
              </span>
              <span className="text-base font-bold" style={{ color: "var(--text-2)" }}>
                ₹3,12,000
              </span>
            </div>
            <div className="mt-0.5 text-[11.5px] font-semibold" style={{ color: "var(--accent)" }}>
              ↑ 5.2% vs last month
            </div>
          </div>
        </Card>
      </div>

      <div
        className="rounded-2xl px-6 py-5"
        style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", borderLeft: "3px solid var(--warning)" }}
      >
        <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: "var(--warning)" }}>
          What Matters Now
        </div>
        <div className="mt-2 max-w-xl text-lg font-semibold" style={{ color: "var(--text-1)" }}>
          Profit is up 15.3% this week — but marketplace fees are quietly offsetting part of the gain.
        </div>
        <div className="mt-3.5 flex flex-wrap items-end gap-6">
          <div>
            <div className="text-2xl font-bold" style={{ color: "var(--warning)" }}>
              -₹18,420 / mo
            </div>
            <div className="mt-0.5 text-[11.5px]" style={{ color: "var(--text-5)" }}>
              Impact this week (est.)
            </div>
          </div>
          <div className="min-w-0 border-l pl-4" style={{ borderColor: "var(--border-default)" }}>
            <div className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-6)" }}>
              Why
            </div>
            <div className="mt-0.5 text-[13px]" style={{ color: "var(--text-3)" }}>
              Amazon referral fees rose 8.4%. 6 SKUs account for 72% of the increase.
            </div>
          </div>
          <div className="min-w-0 border-l pl-4" style={{ borderColor: "var(--border-default)" }}>
            <div className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-6)" }}>
              Recommendation
            </div>
            <div className="mt-0.5 text-[13px]" style={{ color: "var(--text-3)" }}>
              Review the affected SKUs.
            </div>
          </div>
          <span className="ml-auto whitespace-nowrap text-[12.5px] font-bold" style={{ color: "var(--warning)" }}>
            Review SKUs →
          </span>
        </div>
      </div>

      <div>
        <div className="text-[16.5px] font-bold" style={{ color: "var(--text-2)" }}>
          Profit Drivers
        </div>
        <div className="mb-2.5 mt-0.5 text-xs" style={{ color: "var(--text-6)" }}>
          What moved profit this week, ranked by impact
        </div>
        <Card style={{ padding: "6px 22px" }}>
          {[
            { label: "Revenue growth across all channels", value: "+₹52,000", positive: true },
            { label: "Amazon fee increase", value: "-₹18,420", positive: false },
            { label: "Lower return rate on Website orders", value: "+₹9,800", positive: true },
            { label: "Increased ad spend on Flipkart", value: "-₹4,200", positive: false },
          ].map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between gap-2.5 py-3"
              style={{ borderBottom: "1px solid var(--border-subtle)" }}
            >
              <span className="text-[13px]" style={{ color: "var(--text-3)" }}>
                {row.label}
              </span>
              <span
                className="whitespace-nowrap text-[15px] font-bold"
                style={{ color: row.positive ? "var(--accent)" : "var(--negative)" }}
              >
                {row.value}
              </span>
            </div>
          ))}
          <div className="flex items-center justify-between py-3">
            <span className="text-[13px] font-bold" style={{ color: "var(--text-2)" }}>
              Net impact on profit
            </span>
            <span className="text-base font-bold" style={{ color: "var(--accent)" }}>
              +₹39,180
            </span>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-[16.5px] font-bold" style={{ color: "var(--text-2)" }}>
            Profit Leaks
          </div>
          <div className="mb-2.5 mt-0.5 text-xs" style={{ color: "var(--text-6)" }}>
            Where money is slipping away
          </div>
          <div className="flex flex-col gap-2.5">
            <LeakOrOpportunityCard
              title="Marketplace Fees"
              impact="-₹18,420 / mo"
              accent="var(--negative)"
              driver="Amazon referral fees rose 8.4% this week."
              evidence="6 SKUs account for 72% of the increase."
              cta="Review SKUs →"
            />
            <LeakOrOpportunityCard
              title="Return & Refund Costs"
              impact="-₹9,150 / mo"
              accent="var(--negative)"
              driver="Return rate increased on Flipkart orders."
              evidence="Packaging defects flagged on 3 SKUs."
              cta="Review SKUs →"
            />
          </div>
        </div>
        <div>
          <div className="text-[16.5px] font-bold" style={{ color: "var(--text-2)" }}>
            Profit Opportunities
          </div>
          <div className="mb-2.5 mt-0.5 text-xs" style={{ color: "var(--text-6)" }}>
            Where more profit is available
          </div>
          <div className="flex flex-col gap-2.5">
            <LeakOrOpportunityCard
              title="Price Optimization"
              impact="+₹1.82L / mo"
              accent="var(--accent)"
              driver="Portable Mini Blender is priced below market."
              evidence="High demand, low competition on this SKU."
              cta="Review pricing →"
            />
            <LeakOrOpportunityCard
              title="Ad Spend Reallocation"
              impact="+₹51,000 / mo"
              accent="var(--accent)"
              driver="9 days of ROAS below 1.2x on Flipkart ads."
              evidence="Budget could shift to higher-performing campaigns."
              cta="Review campaigns →"
            />
          </div>
        </div>
      </div>

      <div
        className="flex flex-wrap items-center gap-6 rounded-2xl px-6 py-4.5"
        style={{ background: "var(--accent-fill-subtle)", border: "1px solid var(--accent-border-default)", borderLeft: "3px solid var(--accent)" }}
      >
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-wider" style={{ color: "var(--accent)" }}>
            Next Decision
          </div>
          <div className="mt-2 text-[17px] font-semibold" style={{ color: "var(--text-1)" }}>
            Review the 6 SKUs driving the marketplace-fee increase.
          </div>
        </div>
        <div>
          <div className="text-xl font-bold" style={{ color: "var(--accent)" }}>
            ₹18,420 / mo
          </div>
          <div className="text-[11px]" style={{ color: "var(--text-5)" }}>
            Potential monthly impact
          </div>
        </div>
        <button
          type="button"
          className="ml-auto whitespace-nowrap rounded-xl px-4 py-2.5 text-[12.5px] font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          Review SKUs
        </button>
      </div>
    </div>
  );
}

function LeakOrOpportunityCard({
  title,
  impact,
  accent,
  driver,
  evidence,
  cta,
}: {
  title: string;
  impact: string;
  accent: string;
  driver: string;
  evidence: string;
  cta: string;
}) {
  return (
    <Card style={{ borderLeft: `2.5px solid ${accent}`, padding: "16px 18px" }}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-[13.5px] font-semibold" style={{ color: "var(--text-2)" }}>
          {title}
        </div>
        <div className="whitespace-nowrap text-base font-bold" style={{ color: accent }}>
          {impact}
        </div>
      </div>
      <div className="mt-2.5 flex flex-col gap-1.5 pt-2.5" style={{ borderTop: "1px solid var(--border-subtle)" }}>
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          <span className="text-[10.5px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-6)" }}>
            Driver{"  "}
          </span>
          {driver}
        </div>
        <div className="text-xs" style={{ color: "var(--text-3)" }}>
          <span className="text-[10.5px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-6)" }}>
            Evidence{"  "}
          </span>
          {evidence}
        </div>
      </div>
      <div className="mt-3 text-xs font-bold" style={{ color: accent }}>
        {cta}
      </div>
    </Card>
  );
}
