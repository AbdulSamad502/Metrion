"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import { ErrorBanner, Pill, RefreshButton, rise } from "@/components/overview/parts";
import { BANDS_KEY, GAPS_KEY, GOAL_KEY, Goal, Health, Hero, HeroEmpty, HeroSkeleton, LEAKS_KEY, Leaks, PNL_KEY, HEADLINE, figureOf } from "@/components/overview/Overview";
import { daysSince, latestAsOf, STALE_AFTER_DAYS, useBusinessHealth } from "@/lib/useBusinessHealth";
import { useShell } from "@/lib/ShellContext";
import { isOpenRequest } from "@/lib/useNotifications";
import "@/components/overview/overview.css";
import "@/components/cfo/cfo-skin.css";

/** Profit & Finance, to read. Everything here is a saved result the backend presented (`/ceo/state/health`, the CFO data requests and the import list):
 * nothing is calculated in the browser, and nothing on the page asks for input. To work something out, ask the CEO; the forms that used to live here are kept under
 * "Advanced tools" until every one of them has its chat equivalent. */

const ASKS: { icon: IconName; title: string; say: string }[] = [
  { icon: "finance", title: "My profit", say: "What was my profit last month?" },
  { icon: "reports", title: "What changed", say: "Why did my profit change since last month?" },
  { icon: "tag", title: "Pricing", say: "How does my margin change if I set the price to ₹999?" },
  { icon: "products", title: "Buying stock", say: "How many units can I buy with ₹1,00,000?" },
  { icon: "returns", title: "Settlements", say: "Do my settlements match my invoices?" },
  { icon: "alert", title: "Odd numbers", say: "Is anything unusual in my numbers?" },
];

export function FinanceDashboard() {
  const { getToken } = useAuth();
  const { notifications: n } = useShell();
  const { health, refresh, refreshing, checkedAt } = useBusinessHealth();
  const [tick] = useState(0);
  const by = (key: string) => health.entries.find((e) => e.key === key);
  const pnl = by(PNL_KEY);
  const headline = figureOf(pnl, HEADLINE) ?? null;
  const bands = by(BANDS_KEY);
  const leaks = by(LEAKS_KEY);
  const goal = by(GOAL_KEY);
  const inputs = (by(GAPS_KEY)?.presentation?.facts ?? []).map((f) => ({ label: f.label, text: f.text }));
  const requests = n.dataRequests.filter(isOpenRequest);

  const empty = health.entries.length === 0;
  const loading = health.status === "loading" && empty;
  const asOf = latestAsOf(health.entries);
  const age = daysSince(asOf);
  const stale = age !== null && age > STALE_AFTER_DAYS;
  const rightTop = Boolean(bands?.presentation || goal?.presentation?.figures.some((f) => /goal/i.test(f.label)));

  return (
    <div className="ov cfo-skin mt-content" data-testid="finance-dashboard">
      <header className="ov-head ov-rise" style={rise(0)}>
        <div>
          <h2 className="ov-h">Your profit</h2>
          <p className="ov-body" style={{ marginTop: 4 }} role="status">
            {loading ? "Checking your saved results…" : empty ? "Nothing saved yet." : asOf ? `Saved results as of ${asOf.slice(0, 10)}.` : "Saved results."}
          </p>
        </div>
        <div className="ov-head-r">
          {checkedAt && <span className="ov-meta">Updated {new Date(checkedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>}
          <RefreshButton spinning={refreshing} onClick={refresh} />
          <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--brand min-h-10">Ask the CEO <Icon name="arrow" size={14} strokeWidth={2} className="ov-arrow" /></Link>
        </div>
      </header>

      {stale && (
        <div className="ov-note ov-rise" style={rise(1)} role="status" data-testid="data-freshness">
          <span>Your saved results are {age} days old.</span>
          <Link href="#reports" className="ov-btn">Update them</Link>
        </div>
      )}
      {health.status === "error" && !empty && (
        <ErrorBanner message="Couldn’t refresh. Showing the last results that loaded." onRetry={refresh} />
      )}

      <div className="ov-grid">
        <div className={rightTop ? "ov-span-7" : "ov-span-12"} style={{ display: "flex" }}>
          {loading ? <HeroSkeleton /> : pnl && headline ? <Hero pnl={pnl} headline={headline} financeLink={false} /> : <HeroEmpty failed={health.status === "error"} onRetry={refresh} />}
        </div>
        {rightTop && (
          <div className="ov-col ov-span-5">
            {bands && <Health entry={bands} />}
            {goal && <Goal entry={goal} pnl={pnl} />}
          </div>
        )}

        {leaks && (
          <div className="ov-span-6" style={{ display: "flex" }}>
            <Leaks entry={leaks} />
          </div>
        )}
        <div className={leaks ? "ov-span-6" : "ov-span-12"} style={{ display: "flex" }} id="requests">
          <section className="ov-card ov-rise" style={rise(4)} aria-labelledby="fin-needs">
            <div className="ov-card-head">
              <h3 id="fin-needs" className="ov-title">Waiting on you</h3>
              {requests.length > 0 && <Pill tone="warn">{requests.length} open</Pill>}
            </div>
            {requests.length === 0 && inputs.length === 0 ? (
              <div className="ov-empty">
                <span className="ov-badge-circle ov-badge-circle--good"><Icon name="check" size={24} /></span>
                <p className="ov-body">Nothing waiting.</p>
              </div>
            ) : (
              <ul className="ov-rows">
                {requests.slice(0, 4).map((r) => (
                  <li key={r.id}>
                    <Link href="/dashboard/ceo-hub" className="ov-row">
                      <span className="ov-badge-circle ov-badge-circle--warn"><Icon name="finance" size={18} /></span>
                      <span className="ov-row-main">
                        <span className="ov-title">{r.requestedField}</span>
                        <span className="ov-meta">{r.reason ?? "Needed for your profit numbers"}</span>
                      </span>
                      <span className="ov-row-end"><Pill tone="warn">Tell the CEO</Pill></span>
                    </Link>
                  </li>
                ))}
                {inputs.slice(0, Math.max(0, 4 - requests.length)).map((i) => (
                  <li key={i.label}>
                    <Link href="/dashboard/ceo-hub" className="ov-row">
                      <span className="ov-badge-circle ov-badge-circle--warn"><Icon name="tag" size={18} /></span>
                      <span className="ov-row-main">
                        <span className="ov-title">{i.label}</span>
                        <span className="ov-meta">{i.text}</span>
                      </span>
                      <span className="ov-row-end"><Pill tone="warn">Tell the CEO</Pill></span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="ov-span-12" id="reports">
          <section className="ov-card ov-rise" style={rise(5)} aria-labelledby="fin-ask">
            <div className="ov-card-head" style={{ alignItems: "flex-start", flexWrap: "wrap" }}>
              <div>
                <h3 id="fin-ask" className="ov-title">Ask the CEO</h3>
                <p className="ov-meta" style={{ marginTop: 4 }}>Attach reports in chat.</p>
              </div>
            </div>
            <ul className="ci-asks">
              {ASKS.map((a) => (
                <li key={a.title}>
                  <Link href="/dashboard/ceo-hub" className="ov-tile" style={{ height: "100%" }}>
                    <span className="ov-tile-top">
                      <span className="ov-title">{a.title}</span>
                      <span className="ov-badge-circle ov-badge-circle--brand" style={{ width: 32, height: 32 }}><Icon name={a.icon} size={16} /></span>
                    </span>
                    <span className="ov-body" style={{ color: "var(--ov-ink)" }}>“{a.say}”</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="ov-span-12">
          <section className="ov-card ov-rise" style={rise(6)} aria-labelledby="fin-imports">
            <h3 id="fin-imports" className="ov-title">Reports you’ve added</h3>
            <div className="cfo-skin">
              <ImportHistory getToken={getToken} refreshTick={tick} lastUpload={null} />
            </div>
          </section>
        </div>
      </div>

      <p className="ov-meta" style={{ textAlign: "center" }}>
        Want the old forms? <Link href="/dashboard/cfo/tools" className="pi-link">Open the advanced tools</Link>.
      </p>
    </div>
  );
}
