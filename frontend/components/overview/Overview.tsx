"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import type { HealthEntry, PresentationFigure } from "@/lib/ceo";
import { agentMeta, agentTier, useAgentRoster } from "@/lib/agents";
import { useShell } from "@/lib/ShellContext";
import { useBusinessHealth, daysSince, latestAsOf, STALE_AFTER_DAYS } from "@/lib/useBusinessHealth";
import { useCiSummary } from "@/lib/useCiSummary";
import { ALERT_WINDOW_DAYS, isOpenRequest } from "@/lib/useNotifications";
import { BAND_TONE, BAND_WORD, bandOf, dayLabel, flowShares, goalShare, isNegative, periodDays, periodLabel, plainBandLabel, readLeak, registerShort, weight, registerWords } from "./format";
import { Donut } from "./charts";
import { Pill, RefreshButton, rise } from "./parts";
import "./overview.css";

export const PNL_KEY = "BS_PNL_LATEST";
export const BANDS_KEY = "BS_HEALTH_BANDS";
export const LEAKS_KEY = "BS_LEAK_OPEN";
export const GAPS_KEY = "BS_DATA_GAPS";
export const GOAL_KEY = "BS_SELLER_CONTEXT";
export const HEADLINE = "Contribution profit";
const TIER_WORD = { connected: "In chat", available: "Own page", unavailable: "Soon" } as const;
const TAGLINE: Record<string, string> = { CI: "Watches competitor prices", PI: "Finds products to sell", CFO: "Tracks your profit and cash", CMO: "Writes your listings" };

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
export const figureOf = (e: HealthEntry | undefined, label: string) => e?.presentation?.figures.find((f) => f.label === label);

/* ------------------------------------------------------------------ greeting */

function Greeting({ checkedAt, refreshing, onRefresh }: { checkedAt: string | null; refreshing: boolean; onRefresh: () => void }) {
  const { displayName, notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest).length;
  const alerts = n.alerts.length;
  const total = requests + alerts;
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const failed = n.alertsStatus === "error" || n.dataRequestsStatus === "error";
  const first = displayName.split(" ")[0];

  return (
    <header className="ov-head ov-rise" style={rise(0)} data-testid="business-state">
      <div className="ov-head-l">
        <div>
          <h2 className="ov-h">Welcome back, {first}</h2>
          <p className="ov-body" style={{ marginTop: 4 }} role="status">
            {loading ? "Checking what needs you…" : failed ? "We couldn’t check everything." : total === 0 ? "You’re all caught up." : `${total} ${total === 1 ? "thing needs" : "things need"} you.`}
          </p>
        </div>
        {!loading && (total > 0 || failed) && (
          <ul className="ov-chips" aria-label="What needs attention">
            {requests > 0 && (
              <li>
                <Link href="/dashboard/cfo#requests" className="ov-chip ov-chip--warn">
                  <b>{requests}</b> {requests === 1 ? "request" : "requests"} <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" />
                </Link>
              </li>
            )}
            {alerts > 0 && (
              <li>
                <Link href="/dashboard/competitors" className="ov-chip" title={`Last ${ALERT_WINDOW_DAYS} days`}>
                  <b>{alerts}</b> competitor {alerts === 1 ? "alert" : "alerts"} <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" />
                </Link>
              </li>
            )}
            {failed && (
              <li>
                <button type="button" className="ov-chip" onClick={n.reload}>Try again</button>
              </li>
            )}
          </ul>
        )}
      </div>
      <div className="ov-head-r">
        {checkedAt && <span className="ov-meta">Updated {clock(checkedAt)}</span>}
        <RefreshButton spinning={refreshing} onClick={onRefresh} />
      </div>
    </header>
  );
}

/* ------------------------------------------------------------------ hero */

export function Hero({ pnl, headline, financeLink = true }: { pnl: HealthEntry; headline: PresentationFigure; financeLink?: boolean }) {
  const figures = pnl.presentation!.figures;
  const revenue = figures.find((f) => f.label === "Net realized revenue");
  const fees = figures.find((f) => f.label === "Marketplace fees");
  const shares = flowShares(revenue?.value, fees?.value, headline.value);
  const period = periodLabel(pnl.period);
  const negative = isNegative(headline.value);
  const partial = pnl.status !== "COMPLETE" && pnl.status !== "AVAILABLE";

  return (
    <section className="ov-card ov-hero ov-rise" style={rise(1)} aria-labelledby="ov-hero-t" data-testid="profit-hero" data-status={pnl.status}>
      <div className="ov-hero-top">
        <h3 id="ov-hero-t" className="ov-title">{HEADLINE}</h3>
        <span style={{ display: "inline-flex", gap: 8, flexWrap: "wrap" }}>
          {partial && <Pill>{pnl.status.toLowerCase().replace(/_/g, " ")}</Pill>}
          <Pill icon="check">{registerShort(headline.register)}</Pill>
        </span>
      </div>

      <div className="ov-hero-fig">
        <div className="ov-fig-lg" data-testid="figure-value" style={negative ? { color: "#ffd0d6" } : undefined}>{headline.value}</div>
        <p className="ov-meta">{[period, "From your reports"].filter(Boolean).join(" · ")}</p>
      </div>

      {shares && revenue && fees && (
        <div className="ov-flow" data-testid="profit-flow">
          <div
            className="ov-flow-bar"
            role="img"
            aria-label={`Of ${revenue.value} revenue: ${fees.value} went to marketplace fees, ${headline.value} is profit, and the rest covered other costs.`}
          >
            <span className="ov-flow-seg ov-flow-seg--fees" style={{ width: `${shares.fees * 100}%` }} />
            <span className="ov-flow-seg ov-flow-seg--rest" />
            <span className="ov-flow-seg ov-flow-seg--profit" style={{ width: `${shares.profit * 100}%` }} />
          </div>
          <div className="ov-flow-legend">
            <div className="ov-flow-key"><span><i style={{ background: "#ffd48a" }} />Marketplace fees</span><b>{fees.value}</b></div>
            <div className="ov-flow-key"><span><i style={{ background: "rgba(255,255,255,.4)" }} />Other costs</span><Link href="/dashboard/cfo" className="ov-flow-link">See breakdown <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /></Link></div>
            <div className="ov-flow-key"><span><i style={{ background: "#fff" }} />Profit</span><b>{headline.value}</b></div>
          </div>
          <p className="ov-meta">Out of {revenue.value} revenue.</p>
        </div>
      )}

      <div className="ov-hero-actions">
        <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--solid">Ask where profit leaks <Icon name="arrow" size={14} strokeWidth={2} className="ov-arrow" /></Link>
        {financeLink && <Link href="/dashboard/cfo" className="ov-btn ov-btn--glass">Profit &amp; Finance</Link>}
      </div>

      <details className="ov-why">
        <summary><Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /> Where these numbers come from</summary>
        <ul className="ov-why-list">
          {figures.map((f) => (
            <li key={`${f.ref.kind}-${f.ref.id}-${f.label}`} className="ov-why-row">
              <span>{f.label}</span>
              <span><b>{f.value}</b> · {registerWords(f.register)}{f.as_of ? ` · ${dayLabel(f.as_of) ?? f.as_of}` : ""}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export function HeroSkeleton() {
  return (
    <section className="ov-card ov-hero ov-rise" style={rise(1)} aria-label="Loading your saved results" data-testid="health-loading">
      <span className="ov-skel" style={{ width: 160, height: 24 }} />
      <span className="ov-skel" style={{ width: 320, maxWidth: "100%", height: 56 }} />
      <span className="ov-skel" style={{ width: "100%", height: 16 }} />
      <span className="ov-skel" style={{ width: 240, height: 40 }} />
    </section>
  );
}

export function HeroEmpty({ failed, onRetry }: { failed: boolean; onRetry: () => void }) {
  return (
    <section className="ov-card ov-rise" style={rise(1)} data-testid={failed ? "health-unavailable" : "health-none-saved"}>
      <div className="ov-empty">
        <span className="ov-badge-circle"><Icon name={failed ? "alert" : "finance"} size={24} /></span>
        <div>
          <h3 className="ov-h">{failed ? "Couldn’t load your results" : "Let’s get your first numbers"}</h3>
          <p className="ov-body" style={{ marginTop: 8, maxWidth: "48ch" }}>
            {failed ? "Try again in a moment." : "Upload your reports to see your profit."}
          </p>
        </div>
        {failed ? (
          <button type="button" className="ov-btn" onClick={onRetry}>Try again</button>
        ) : (
          <Link href="/dashboard/cfo#reports" className="ov-btn" style={{ background: "var(--ov-brand)", color: "#fff" }}>Upload reports <Icon name="arrow" size={14} strokeWidth={2} className="ov-arrow" /></Link>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ side cards */

const BAND_KEY = { GOOD: "good", WATCH: "to watch", AT_RISK: "at risk" } as const;
const BAND_COLOR = { GOOD: "var(--ov-good)", WATCH: "var(--ov-warn)", AT_RISK: "var(--ov-bad)" } as const;

export function Health({ entry }: { entry: HealthEntry }) {
  const p = entry.presentation;
  if (!p) return null;
  const overall = bandOf(p.facts.find((f) => /overall/i.test(f.label))?.text);
  const rows = p.figures.map((f) => ({ f, band: bandOf(f.value) }));
  const counted = rows.filter((r) => r.band).length;
  const counts = counted >= 2 ? { GOOD: rows.filter((r) => r.band === "GOOD").length, WATCH: rows.filter((r) => r.band === "WATCH").length, AT_RISK: rows.filter((r) => r.band === "AT_RISK").length } : null;
  return (
    <section className="ov-card ov-rise" style={rise(2)} aria-labelledby="ov-health" data-testid={`health-${entry.key}`}>
      <div className="ov-card-head">
        <h3 id="ov-health" className="ov-title">Business health</h3>
        {overall && <Pill tone={BAND_TONE[overall]} icon={overall === "GOOD" ? "check" : "alert"}>{BAND_WORD[overall]}</Pill>}
      </div>
      {counts && (
        <div className="ov-chart">
          <Donut
            parts={(["GOOD", "WATCH", "AT_RISK"] as const).filter((b) => counts[b] > 0).map((b) => ({ key: b, label: BAND_WORD[b], share: counts[b] / counted, color: BAND_COLOR[b] }))}
            summary={`${counts.GOOD} of ${counted} checks are good, ${counts.WATCH} to watch, ${counts.AT_RISK} at risk.`}
            size={144}
            center={<><span className="ov-fig">{counts.GOOD}/{counted}</span><span className="ov-meta">good</span></>}
          />
          <ul className="ov-chart-key">
            {(["GOOD", "WATCH", "AT_RISK"] as const).map((b) => <li key={b}><i style={{ background: BAND_COLOR[b] }} aria-hidden />{BAND_KEY[b]}<b>{counts[b]}</b></li>)}
          </ul>
        </div>
      )}
      <ul className="ov-rows">
        {rows.map(({ f, band }) => (
          <li key={f.label} className="ov-row" style={{ minHeight: 48 }}>
            <span className="ov-row-main"><span className="ov-body" style={{ color: "var(--ov-ink)" }}>{plainBandLabel(f.label)}</span></span>
            {band ? <Pill tone={BAND_TONE[band]} icon={band === "GOOD" ? "check" : "alert"}>{BAND_WORD[band]}</Pill> : <span className="ov-meta">{f.value}</span>}
          </li>
        ))}
      </ul>
      {periodLabel(entry.period) && <p className="ov-meta">{periodLabel(entry.period)}</p>}
    </section>
  );
}

export function Leaks({ entry }: { entry: HealthEntry }) {
  const p = entry.presentation;
  if (!p || p.figures.length === 0) return null;
  const leaks = p.figures.map(readLeak);
  const biggest = Math.max(1, ...leaks.map((l) => Math.abs(weight(l.amount) ?? 0)));
  const more = p.gaps.length > 0;
  return (
    <section className="ov-card ov-rise" style={rise(3)} aria-labelledby="ov-leaks" data-testid={`health-${entry.key}`}>
      <div className="ov-card-head">
        <h3 id="ov-leaks" className="ov-title">Money slipping away</h3>
        <Link href="/dashboard/cfo" className="ov-btn ov-btn--ghost" aria-label="See all open leaks">See all <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /></Link>
      </div>
      <ul className="ov-rows">
        {leaks.map((l) => (
          <li key={l.key}>
            <Link href="/dashboard/cfo" className="ov-row">
              <span className={`ov-badge-circle ov-badge-circle--${l.severity === "High" ? "bad" : l.severity === "Medium" ? "warn" : ""}`}><Icon name="alert" size={18} /></span>
              <span className="ov-row-main">
                <span className="ov-title">{l.title}</span>
                <span className="ov-meta">{[l.where, l.severity ? `${l.severity} priority` : null].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="ov-row-end"><span className="ov-amount">{l.amount}</span></span>
              <span className="ov-leakbar" aria-hidden><i style={{ width: `${Math.max(4, ((weight(l.amount) ?? 0) / biggest) * 100)}%` }} /></span>
            </Link>
          </li>
        ))}
      </ul>
      {more && <p className="ov-meta">More in Profit &amp; Finance.</p>}
    </section>
  );
}

export function Goal({ entry, pnl }: { entry: HealthEntry; pnl: HealthEntry | undefined }) {
  const goal = entry.presentation?.figures.find((f) => /goal/i.test(f.label));
  if (!goal) return null;
  const profit = figureOf(pnl, HEADLINE);
  const days = periodDays(pnl?.period);
  const share = days !== null && days >= 28 && days <= 31 ? goalShare(profit?.value, goal.value) : null;
  return (
    <section className="ov-card ov-rise" style={rise(4)} aria-labelledby="ov-goal">
      <div className="ov-card-head">
        <h3 id="ov-goal" className="ov-title">Your monthly goal</h3>
        <Pill tone="brand">Set by you</Pill>
      </div>
      <div className="ov-fig">{goal.value}</div>
      {share !== null && profit && (
        <>
          <div className="ov-meter" role="img" aria-label={`Latest profit ${profit.value} against a goal of ${goal.value}`}><i style={{ width: `${share * 100}%` }} /></div>
          <p className="ov-meta">Latest profit {profit.value}</p>
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ needs you */

function NeedsYou({ inputs }: { inputs: { label: string; text: string }[] }) {
  const { notifications: n } = useShell();
  const requests = n.dataRequests.filter(isOpenRequest);
  const alerts = [...n.alerts].sort((a, b) => Number(b.thresholdBreached) - Number(a.thresholdBreached));
  const loading = n.alertsStatus === "loading" || n.dataRequestsStatus === "loading";
  const failed = [n.alertsError, n.dataRequestsError].filter((e): e is string => Boolean(e));
  const rows = requests.length + alerts.length + inputs.length;
  const MAX = 4; // a short list reads as "doable"; the rest is one click away
  const shownRequests = requests.slice(0, MAX);
  const shownAlerts = alerts.slice(0, MAX - shownRequests.length);
  const shownInputs = inputs.slice(0, MAX - shownRequests.length - shownAlerts.length);

  return (
    <section className="ov-card ov-rise" style={rise(5)} aria-labelledby="ov-needs">
      <div className="ov-card-head">
        <h3 id="ov-needs" className="ov-title">Needs you</h3>
        {rows > 0 && <Link href="/dashboard/notifications" className="ov-btn ov-btn--ghost" aria-label="See everything that needs you">{rows > MAX ? `See all ${rows}` : "See all"} <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /></Link>}
      </div>
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }} aria-label="Loading what needs you">
          {[0, 1, 2].map((i) => <span key={i} className="ov-skel" style={{ height: 48 }} />)}
        </div>
      ) : (
        <>
          {failed.length > 0 && (
            <div className="ov-note ov-note--bad" role="alert">
              <span>{failed[0]}</span>
              <button type="button" className="ov-btn" onClick={n.reload}>Try again</button>
            </div>
          )}
          {rows === 0 && failed.length === 0 ? (
            <div className="ov-empty">
              <span className="ov-badge-circle ov-badge-circle--good"><Icon name="check" size={24} /></span>
              <p className="ov-body">Nothing needs you.</p>
            </div>
          ) : (
            <ul className="ov-rows">
              {shownRequests.map((r) => (
                <li key={r.id}>
                  <Link href="/dashboard/cfo#requests" className="ov-row">
                    <span className="ov-badge-circle ov-badge-circle--warn"><Icon name="finance" size={18} /></span>
                    <span className="ov-row-main">
                      <span className="ov-title">{r.requestedField}</span>
                      <span className="ov-meta">{r.reason ?? "Needed for your profit numbers"}</span>
                    </span>
                    <span className="ov-row-end"><Pill tone="warn">Add</Pill></span>
                  </Link>
                </li>
              ))}
              {shownAlerts.map((a) => (
                <li key={a.priceEventId}>
                  <Link href="/dashboard/competitors" className="ov-row">
                    <span className={`ov-badge-circle ${a.thresholdBreached ? "ov-badge-circle--bad" : "ov-badge-circle--brand"}`}><Icon name="competitors" size={18} /></span>
                    <span className="ov-row-main">
                      <span className="ov-title">{a.competitorLabel}</span>
                      <span className="ov-meta">{a.message}</span>
                    </span>
                    <span className="ov-row-end"><Pill tone={a.thresholdBreached ? "bad" : "brand"}>{a.thresholdBreached ? "Big move" : "Review"}</Pill></span>
                  </Link>
                </li>
              ))}
              {shownInputs.map((i) => (
                <li key={i.label}>
                  <Link href="/dashboard/cfo#reports" className="ov-row">
                    <span className="ov-badge-circle ov-badge-circle--warn"><Icon name="tag" size={18} /></span>
                    <span className="ov-row-main">
                      <span className="ov-title">{i.label}</span>
                      <span className="ov-meta">{i.text}</span>
                    </span>
                    <span className="ov-row-end"><Pill tone="warn">Add</Pill></span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ market */

function Market({ ci }: { ci: ReturnType<typeof useCiSummary> }) {
  const { summary } = ci;
  if (ci.forbidden) return null;
  const tiles: { label: string; value: number | null; warn?: boolean; hint?: string }[] = [
    { label: "Competitors", value: summary?.trackedCompetitors ?? null, hint: summary?.lastResearchAt ? `Checked ${dayLabel(summary.lastResearchAt.slice(0, 10))}` : "Not checked yet" },
    { label: "Price changes", value: summary?.recentPriceEvents7d ?? null, hint: "Last 7 days" },
    { label: "Unreadable", value: summary?.pendingManualEntry ?? null, warn: (summary?.pendingManualEntry ?? 0) > 0, hint: "Add by hand" },
    { label: "Out of date", value: summary?.staleCompetitors ?? null, warn: (summary?.staleCompetitors ?? 0) > 0, hint: `Over ${STALE_AFTER_DAYS} days` },
  ];
  return (
    <section className="ov-card ov-rise" style={rise(6)} aria-labelledby="ov-market" data-testid="market-watch">
      <div className="ov-card-head">
        <h3 id="ov-market" className="ov-title">Competitors</h3>
        <Link href="/dashboard/competitors" className="ov-btn ov-btn--ghost" aria-label="Open competitors">Open <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /></Link>
      </div>
      {ci.error && !summary ? (
        <div className="ov-note ov-note--bad" role="alert"><span>{ci.error}</span><button type="button" className="ov-btn" onClick={ci.reload}>Try again</button></div>
      ) : (
        <div className="ov-tiles">
          {tiles.map((t) => (
            <Link key={t.label} href="/dashboard/competitors" className={`ov-tile${t.warn ? " ov-tile--warn" : ""}`}>
              <span className="ov-tile-top">
                <span className="ov-meta">{t.label}</span>
                {t.warn && <Icon name="alert" size={14} />}
              </span>
              {t.value === null ? <span className="ov-skel" style={{ height: 32, width: 48 }} aria-label="Loading" /> : <span className="ov-fig">{t.value}</span>}
              <span className="ov-meta">{t.hint}</span>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ team */

function Team({ lastResearchAt }: { lastResearchAt: string | null | undefined }) {
  const { agents, error, reload } = useAgentRoster();
  return (
    <section aria-labelledby="ov-team" className="ov-rise" style={{ ...rise(7), display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="ov-card-head">
        <h3 id="ov-team" className="ov-title">Your team</h3>
        <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--ghost">Ask the CEO <Icon name="arrow" size={12} strokeWidth={2} className="ov-arrow" /></Link>
      </div>
      {error ? (
        <div className="ov-note ov-note--bad" role="alert"><span>{error}</span><button type="button" className="ov-btn" onClick={reload}>Try again</button></div>
      ) : !agents ? (
        <div className="ov-team" aria-label="Loading your team">{[0, 1, 2, 3].map((i) => <span key={i} className="ov-skel" style={{ height: 152, borderRadius: 24 }} />)}</div>
      ) : (
        <ul className="ov-team">
          {agents.map((a) => {
            const meta = agentMeta(a.id);
            const tier = agentTier(a);
            const last = a.id === "CI" && lastResearchAt ? `Last checked ${dayLabel(lastResearchAt.slice(0, 10))}` : (TAGLINE[a.id] ?? meta.role);
            const body = (
              <>
                <span className="ov-agent-top">
                  <span className="ov-badge-circle"><Icon name={meta.icon} size={20} /></span>
                  <span className="ov-pill"><i className={`ov-dot${tier === "connected" ? " ov-dot--good" : ""}`} />{TIER_WORD[tier]}</span>
                </span>
                <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span className="ov-title">{a.name}</span>
                  <span className="ov-meta">{TAGLINE[a.id] ?? meta.role}</span>
                  {a.id === "CI" && lastResearchAt && <span className="ov-meta">{last}</span>}
                </span>
              </>
            );
            return <li key={a.id} style={{ display: "flex" }}>{meta.href ? <Link href={meta.href} className="ov-agent" style={{ flex: 1 }} aria-label={`Open ${a.name}`}>{body}</Link> : <div className="ov-agent" style={{ flex: 1 }}>{body}</div>}</li>;
          })}
        </ul>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ page */

export function Overview() {
  const ci = useCiSummary();
  const { health, refresh, refreshing, checkedAt } = useBusinessHealth();
  const by = (key: string) => health.entries.find((e) => e.key === key);
  const pnl = by(PNL_KEY);
  const headline = figureOf(pnl, HEADLINE) ?? null;
  const bands = by(BANDS_KEY);
  const leaks = by(LEAKS_KEY);
  const goal = by(GOAL_KEY);
  const inputs = (by(GAPS_KEY)?.presentation?.facts ?? []).map((f) => ({ label: f.label, text: f.text }));

  const rightTop = Boolean(bands?.presentation || goal?.presentation?.figures.some((f) => /goal/i.test(f.label)));
  const empty = health.entries.length === 0;
  const loading = health.status === "loading" && empty;
  const asOf = latestAsOf(health.entries);
  const age = daysSince(asOf);
  const stale = age !== null && age > STALE_AFTER_DAYS;

  return (
    <div className="ov mt-content">
      <Greeting checkedAt={checkedAt} refreshing={refreshing} onRefresh={refresh} />

      {stale && (
        <div className="ov-note ov-rise" style={rise(1)} role="status" data-testid="data-freshness">
          <span>Your saved results are {age} days old.</span>
          <Link href="/dashboard/cfo#reports" className="ov-btn">Upload new reports</Link>
        </div>
      )}
      {health.status === "error" && !empty && (
        <div className="ov-note ov-note--bad" role="alert">
          <span>Couldn’t refresh. Showing the last results that loaded.</span>
          <button type="button" className="ov-btn" onClick={refresh}>Try again</button>
        </div>
      )}

      <div className="ov-grid">
        <div className={rightTop ? "ov-span-7" : "ov-span-12"} style={{ display: "flex" }}>
          {loading ? <HeroSkeleton /> : pnl && headline ? <Hero pnl={pnl} headline={headline} /> : <HeroEmpty failed={health.status === "error"} onRetry={refresh} />}
        </div>
        {rightTop && (
          <div className="ov-col ov-span-5">
            {bands && <Health entry={bands} />}
            {goal && <Goal entry={goal} pnl={pnl} />}
          </div>
        )}

        <div className={leaks ? "ov-span-7" : "ov-span-12"} style={{ display: "flex" }}>
          <NeedsYou inputs={inputs} />
        </div>
        {leaks && (
          <div className="ov-span-5" style={{ display: "flex" }}>
            <Leaks entry={leaks} />
          </div>
        )}

        <div className="ov-span-12"><Market ci={ci} /></div>
        <div className="ov-span-12"><Team lastResearchAt={ci.summary?.lastResearchAt} /></div>
      </div>
    </div>
  );
}
