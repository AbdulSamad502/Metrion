"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { Pill, RefreshButton, rise } from "@/components/overview/parts";
import { ApiError, type MarketOverview, type MetricResult } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import {
  askFindingHref, askHref, groupEvents, findingText, fmtDate, fmtDateTime, FRESHNESS_LABEL, offersLine, PRICE_STATUS_LABEL, productLabel, RELATIONSHIP_LABEL, themeList, unavailableWords,
  type CiCandidate, type CiCompetitor, type CiWorkspace,
} from "@/lib/ciWorkspace";
import { formatPaise } from "@/lib/piShowcase";
import { dayLabel } from "@/components/overview/format";
import { PriceStrip, type StripBand } from "./PriceStrip";
import "@/components/overview/overview.css";
import "./ci.css";

/** The read-only Competitor Intelligence dashboard (docs/specs/competitor-intelligence-agent.md §6.29).
 * It shows what CEO-CI investigations already produced. There is no form, no input, no upload and no control that changes data: the buttons switch what is shown, and every
 * action is a link into the CEO Hub (the only place the seller asks, uploads or confirms). Every figure is stored by the backend or the engine; a missing value says so and why. */

/** A link into the CEO Hub. `primary` is the one next step (white on the hero), `secondary` is a calm button, `quiet` is a text action. Every one keeps a 40px target. */
function AskCeo({ href, label, quiet = false, variant }: { href: string; label: string; quiet?: boolean; variant?: "primary" | "secondary" | "quiet" }) {
  const level = variant ?? (quiet ? "quiet" : "primary");
  const cls = level === "primary" ? "ov-btn ov-btn--solid" : level === "secondary" ? "ov-btn" : "ov-btn ov-btn--ghost";
  return (
    <Link href={href} className={`${cls} min-h-10 whitespace-nowrap`}>
      {label}
    </Link>
  );
}

function Tile({ label, value, hint, tone, meter }: { label: string; value: string | number | null; hint: ReactNode; tone?: "warn"; meter?: { used: number; limit: number } }) {
  return (
    <div className={`ov-tile${tone === "warn" ? " ov-tile--warn" : ""}`}>
      <span className="ov-tile-top">
        <span className="ov-meta">{label}</span>
        {tone === "warn" && <Icon name="alert" size={14} />}
      </span>
      <span className="ov-fig" style={value === null ? { color: "var(--ov-ink-3)" } : undefined}>{value === null ? "Not available" : value}</span>
      {meter && (
        <span className="ci-seg" aria-hidden>
          {Array.from({ length: meter.limit }, (_, i) => <i key={i} className={i < meter.used ? "on" : ""} />)}
        </span>
      )}
      <span className="ov-meta">{hint}</span>
    </div>
  );
}

function Box({ title, subtitle, children, action, index = 2 }: { title: string; subtitle?: string; children: ReactNode; action?: ReactNode; index?: number }) {
  return (
    <section className="ov-card ov-rise" style={rise(index)}>
      <div className="ov-card-head">
        <div>
          <h2 className="ov-title">{title}</h2>
          {subtitle && <p className="ov-meta" style={{ marginTop: 4 }}>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export type CiClient = {
  workspace(productId: string | null): Promise<CiWorkspace>;
  market(productId: string): Promise<MarketOverview>;
};

const bandRow = (rows: MetricResult[], key: string) => rows.find((r) => r.isAvailable && (r.calculationBasis ?? "").includes(`PriceBand ${key} `));

type Pending = { productId: string | null; kind: "switch" | "refresh" };
type LoadFailure = { message: string; productId: string | null; kind: "switch" | "refresh" };

export function CiDashboard({ client }: { client: CiClient }) {
  const [ws, setWs] = useState<CiWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [market, setMarket] = useState<MarketOverview | null>(null);
  const [marketNote, setMarketNote] = useState<string | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  // What this page did last: a switch or refresh in flight, the last one that failed, and when the shown data was last fetched (this browser's clock).
  const [pending, setPending] = useState<Pending | null>(null);
  const [failure, setFailure] = useState<LoadFailure | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const seq = useRef(0); // only the latest request may change the screen: a slower, older reply is dropped
  const hasData = useRef(false);

  const load = useCallback(
    async (productId: string | null, kind: "initial" | "switch" | "refresh" = "initial") => {
      const mine = ++seq.current;
      if (kind !== "initial") setPending({ productId, kind });
      setFailure(null);
      try {
        const data = await client.workspace(productId);
        if (mine !== seq.current) return;
        hasData.current = true;
        setWs(data);
        setError(null);
        setMarket(null);
        setMarketNote(null);
        setCheckedAt(new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" }));
        setPending(null);
        if (data.selectedProductId && !data.selectedProductId.startsWith("category:")) {
          setMarketLoading(true);
          try {
            const m = await client.market(data.selectedProductId);
            if (mine === seq.current) setMarket(m);
          } catch (e) {
            if (mine === seq.current) setMarketNote(friendlyApiError(e, "The market band could not be loaded."));
          } finally {
            if (mine === seq.current) setMarketLoading(false);
          }
        }
      } catch (e) {
        if (mine !== seq.current) return;
        setPending(null);
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else if (hasData.current && kind !== "initial") {
          // What is already on screen stays, and says so: a failed switch or refresh must not blank a workspace that did load.
          setFailure({ message: friendlyApiError(e, "Could not load the competitor workspace."), productId, kind });
        } else setError(friendlyApiError(e, "Could not load the competitor workspace."));
      }
    },
    [client],
  );

  useEffect(() => {
    (async () => {
      await load(null);
    })();
  }, [load]);

  if (forbidden) return <EmptyState title="Your role does not include Competitor Intelligence" description="Ask the account owner to give you access." />;
  if (error && !ws) return <ErrorNotice message={error} onRetry={() => void load(null)} />;
  if (!ws) return <LoadingState lines={4} label="Loading competitor intelligence" />;

  const selected = ws.products.find((p) => p.productId === ws.selectedProductId) ?? null;
  const subject = selected ? productLabel(selected) : null;
  const k = ws.kpis;
  const bandAvailable = !!market && market.rows.some((r) => r.isAvailable);
  const verifiedPrices = ws.competitors.filter((c) => c.priceStatus === "VERIFIED" && c.listedPricePaise !== null);
  const shownProduct = pending?.kind === "switch" ? pending.productId : ws.selectedProductId;
  const act = nextAction(ws);
  const bandPaise = (key: string) => (market ? (bandRow(market.rows, key)?.valuePaise ?? null) : null);
  const stripBand: StripBand | null =
    bandAvailable && bandPaise("Q1") !== null && bandPaise("Q3") !== null && bandPaise("TYPICAL_LOW") !== null && bandPaise("TYPICAL_HIGH") !== null
      ? { q1: bandPaise("Q1")!, q3: bandPaise("Q3")!, low: bandPaise("TYPICAL_LOW")!, high: bandPaise("TYPICAL_HIGH")! }
      : null;
  const hasAny = k.trackedCount > 0 || ws.candidates.length > 0;

  return (
    <div className="ov mt-content" data-testid="ci-dashboard">
      <div className="ov-rise" style={rise(0)}>
        <h2 className="ov-h">How you compare</h2>
        <p className="ov-body" style={{ marginTop: 4 }}>Verified prices, changes and what customers say</p>
      </div>
      <header className="ov-head ov-rise" style={rise(0)}>
        <div className="ov-chips-row" role="group" aria-label="Product shown">
          {ws.products.length === 0 ? (
            <span className="ov-body">No products yet</span>
          ) : (
            ws.products.map((p) => (
              <button
                key={p.productId}
                type="button"
                aria-pressed={p.productId === shownProduct}
                aria-busy={pending?.kind === "switch" && pending.productId === p.productId}
                onClick={() => {
                  // The product on screen, or the one already being loaded, needs no second request.
                  if (p.productId === ws.selectedProductId && !pending) return;
                  if (pending?.kind === "switch" && pending.productId === p.productId) return;
                  void load(p.productId, "switch");
                }}
                className="ci-pick mt-focus"
              >
                {productLabel(p)}
              </button>
            ))
          )}
        </div>
        <div className="ov-head-r">
          <Link href={askHref("research", null)} className="ov-btn min-h-10">Find competitors</Link>
          <Link href={askHref("track", null)} className="ov-btn ov-btn--ghost min-h-10">Track a competitor</Link>
        </div>
      </header>

      {/* where this data comes from: which product, as of when, and whether it is being replaced right now */}
      <div className="ov-head-r ov-rise" style={{ ...rise(1), justifyContent: "space-between" }} data-testid="ci-context-row">
        <p role="status" className="ov-meta" data-testid="ci-context" style={{ margin: 0 }}>
          {pending?.kind === "switch"
            ? `Loading ${ws.products.find((p) => p.productId === pending.productId)?.title ?? "the next product"}… the ${subject ?? "tracked competitors"} view below is the previous one.`
            : pending?.kind === "refresh"
              ? "Refreshing… what is shown is the last result that loaded."
              : `Data as of ${fmtDateTime(ws.asOf)}${checkedAt ? ` · checked ${checkedAt}` : ""}`}
        </p>
        <RefreshButton spinning={pending?.kind === "refresh"} onClick={() => void load(ws.selectedProductId, "refresh")} />
      </div>
      {failure && (
        <ErrorNotice
          message={`${failure.message} ${failure.kind === "switch" ? `Still showing ${subject ?? "the previous view"}.` : "What is shown may be out of date."}`}
          onRetry={() => void load(failure.productId, failure.kind)}
        />
      )}

      <div className="ov" style={{ opacity: pending ? 0.6 : 1, transition: "opacity 200ms ease", maxWidth: "none", margin: 0 }} aria-busy={pending !== null}>
        {!hasAny ? (
          <section className="ov-card ov-rise" style={rise(2)}>
            <EmptyState
              icon="competitors"
              title="No competitors tracked yet"
              description="Find rivals, send screenshots, see what changed. It starts in a chat with the CEO. Nothing here is estimated or sample data."
              action={<AskCeo href={askHref("research", subject)} label="Find competitors" variant="secondary" />}
            />
          </section>
        ) : (
          <>
            <div className="ov-grid">
              <section className="ov-card ov-hero ci-next ov-span-7 ov-rise" style={rise(2)} aria-labelledby="ci-next-t">
                <h2 id="ci-next-t" className="ov-title">What to do next</h2>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <p className="ov-h">{nextHeadline(ws)}</p>
                  <p className="ov-body">{nextStep(ws)}</p>
                </div>
                <div className="ci-next-actions"><AskCeo href={act.href} label={act.label} /></div>
              </section>
              <div className="ov-span-5">
                <div className="ov-tiles ci-tiles ov-rise" style={{ ...rise(3), height: "100%" }}>
                  <Tile label="Competitors tracked" value={ws.watchlist ? `${ws.watchlist.used} of ${ws.watchlist.limit}` : k.trackedCount} meter={ws.watchlist ? { used: ws.watchlist.used, limit: ws.watchlist.limit } : undefined} hint={ws.watchlist && ws.watchlist.free === 0 ? "Full: stop one to add another" : `${k.verifiedCount} with a verified price`} />
                  <Tile label="Need fresh evidence" value={k.needsEvidenceCount} tone={k.needsEvidenceCount > 0 ? "warn" : undefined} hint={k.needsEvidenceCount > 0 ? "Send a new screenshot" : "All evidence is recent"} />
                  <Tile label="Verified changes" value={k.importantChangeCount} hint="Price or stock" />
                  <Tile label="Customer insights" value={k.reviewInsightCount} hint="From your screenshots" />
                </div>
              </div>

              <div className="ov-span-12" style={{ display: "flex" }}>
                <Box title="Where your price sits" subtitle="Verified prices only" index={4}>
                  {ws.selectedProductId?.startsWith("category:") ? (
                    <EmptyState
                      compact
                      title="Compare your price with these competitors"
                      description="Tracked for a category. Tell the CEO your price to compare."
                      action={<AskCeo href={askHref("compare", null)} label="Compare my price" variant="secondary" />}
                    />
                  ) : marketLoading ? (
                    <LoadingState lines={2} label="Loading the price band" />
                  ) : bandAvailable && market ? (
                    <>
                      <PriceStrip points={verifiedPrices.map((c) => ({ id: c.id, label: c.label ?? "Competitor", paise: c.listedPricePaise! }))} band={stripBand} />
                      <dl className="ci-band-dl">
                        {[["Q1", "Q1"], ["Q3", "Q3"], ["Typical low", "TYPICAL_LOW"], ["Typical high", "TYPICAL_HIGH"]].map(([label, key]) => (
                          <div key={key}>
                            <dt>{label}</dt>
                            <dd>{formatPaise(bandRow(market.rows, key)?.valuePaise)}</dd>
                          </div>
                        ))}
                      </dl>
                    </>
                  ) : (
                    <>
                      <EmptyState
                        compact
                        title="No price band yet"
                        description={
                          marketNote ??
                          (market && market.rows[0]?.unavailableReason
                            ? `${market.rows[0].unavailableReason}. Needs ${market.minCompetitorsRequired}+ verified prices.`
                            : "A band needs a few verified prices.")
                        }
                      />
                      {verifiedPrices.length > 0 && <PriceStrip points={verifiedPrices.map((c) => ({ id: c.id, label: c.label ?? "Competitor", paise: c.listedPricePaise! }))} band={null} />}
                    </>
                  )}
                </Box>
              </div>
              <div className="ov-span-12" style={{ display: "flex" }}>
                <Box title="Insights" index={5}>
                  <Insights ws={ws} subject={subject} />
                </Box>
              </div>
            </div>

            <Box title="Tracked competitors" index={6}>
              {ws.competitors.length === 0 ? (
                <EmptyState compact title="No competitors tracked for this product" description="Ask the CEO to find some." action={<AskCeo href={askHref("research", subject)} label="Find competitors" />} />
              ) : (
                <CompetitorTable rows={ws.competitors} />
              )}
            </Box>

            <Box title="Found, awaiting your decision" subtitle="Not verified yet" index={7}>
              {ws.candidates.length === 0 ? (
                <EmptyState compact title="No candidates waiting" description={ws.lastDiscovery ? discoveryNote(ws.lastDiscovery) : "No search yet."} />
              ) : (
                <CandidateList rows={ws.candidates} />
              )}
            </Box>

            <div className="ov-grid">
              <div className="ov-span-7" style={{ display: "flex" }}>
                <Box title="Verified changes" subtitle="Dated screenshots, not live" index={8}>
                  {ws.changes.length === 0 ? (
                    <EmptyState compact title="No verified changes yet" description="Shows after a second confirmed screenshot." />
                  ) : (
                    <Changes ws={ws} />
                  )}
                </Box>
              </div>
              <div className="ov-span-5" style={{ display: "flex" }}>
                <Box title="Review insights" subtitle="Recurring themes" index={11}>
                  {ws.reviewInsights.length === 0 ? (
                    <EmptyState compact title="No review insights yet" description="Send the CEO a reviews screenshot." action={<AskCeo href={askHref("reviews", null)} label="Ask about reviews" />} />
                  ) : (
                    <ul className="ci-list">
                      {ws.reviewInsights.map((r) => (
                        <li key={r.competitorId} className="ci-change">
                          <span className="ov-title">{r.label ?? "A competitor"}</span>
                          <span className="ov-meta">
                            {r.reviewsConsidered ? `${r.reviewsConsidered} reviews read` : "Sample size not stated"} · {fmtDate(r.evidenceDate)} · confidence {r.confidence.toLowerCase()}
                          </span>
                          {themeList(r.complaintThemes).length > 0 && <p className="ov-body" style={{ color: "var(--ov-ink)" }}>Complaints: {themeList(r.complaintThemes).join(", ")}</p>}
                          {themeList(r.positiveThemes).length > 0 && <p className="ov-body" style={{ color: "var(--ov-ink)" }}>Praised: {themeList(r.positiveThemes).join(", ")}</p>}
                          <span className="ci-actions">
                            <AskCeo href={askHref("reviewsfor", r.label)} label="Add more reviews" quiet />
                            {r.findingId && <AskCeo href={askFindingHref(r.findingId, ws.selectedProductId, r.label)} label="Explain this" quiet />}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Box>
              </div>
              <div className="ov-span-7" style={{ display: "flex" }}>
                <Box title="Freshness" index={9}>
                  {ws.competitors.length === 0 ? (
                    <EmptyState compact title="Nothing to check yet" description="Shows once a competitor is tracked." />
                  ) : (
                    <ul className="ov-rows ci-fresh">
                      {ws.competitors.map((c) => {
                        const behind = daysBehind(c.evidenceDate, ws.competitors.map((x) => x.evidenceDate));
                        return (
                        <li key={c.id} className="ov-row" style={{ minHeight: 56 }}>
                          <span className="ov-row-main">
                            <span className="ov-title">{c.label ?? "Competitor"}</span>
                            <span className="ov-meta">{c.evidenceDate ? fmtDate(c.evidenceDate) : "no screenshot yet"}{behind && behind.days > 0 ? ` · ${behind.days} day${behind.days === 1 ? "" : "s"} behind the newest` : ""}</span>
                            {behind && <span className="ci-age" aria-hidden><i className={c.freshness === "FRESH" ? undefined : "is-old"} style={{ width: `${Math.max(4, 100 - behind.share * 100)}%` }} /></span>}
                          </span>
                          <Pill tone={c.freshness === "FRESH" ? "good" : "warn"} icon={c.freshness === "FRESH" ? "check" : "alert"}>{FRESHNESS_LABEL[c.freshness]}</Pill>
                        </li>
                        );
                      })}
                    </ul>
                  )}
                </Box>
              </div>
              <div className="ov-span-5" style={{ display: "flex" }}>
                <Box title="Waiting on you" index={10}>
                  {ws.pendingConfirmations.length === 0 ? (
                    <EmptyState compact title="Nothing waiting" description="Details to confirm show up here." />
                  ) : (
                    <ul className="ci-list">
                      {ws.pendingConfirmations.map((p) => (
                        <li key={p.id} className="ci-item">
                          <span className="ci-item-main">
                            <span className="ov-title">Confirm the {p.field.replace(/_paise$/, "").replace(/_/g, " ")}</span>
                            <span className="ov-meta">until {fmtDate(p.expiresAt)}</span>
                          </span>
                          <AskCeo href={askHref("confirm", null)} label="Confirm in chat" quiet />
                        </li>
                      ))}
                    </ul>
                  )}
                </Box>
              </div>
            </div>

            <Box title="History" index={12}>
              <Activity ws={ws} limit={40} />
            </Box>
          </>
        )}
      </div>
    </div>
  );
}

function nextHeadline(ws: CiWorkspace): string {
  const k = ws.kpis;
  if (k.trackedCount === 0) return "Let’s find your competitors";
  if (k.pendingQuestionCount > 0) return `${k.pendingQuestionCount} ${k.pendingQuestionCount === 1 ? "detail needs" : "details need"} your OK`;
  if (k.needsEvidenceCount > 0) return `${k.needsEvidenceCount} ${k.needsEvidenceCount === 1 ? "competitor needs" : "competitors need"} a new screenshot`;
  return "Your evidence is current";
}

function nextStep(ws: CiWorkspace): string {
  const k = ws.kpis;
  if (k.trackedCount === 0) return "Find some and pick the ones to track.";
  if (k.pendingQuestionCount > 0) return "Confirm them in chat.";
  if (k.needsEvidenceCount > 0) return "Send fresh screenshots to the CEO.";
  return "Compare your price, or add a reviews screenshot.";
}

function nextAction(ws: CiWorkspace): { href: string; label: string } {
  const k = ws.kpis;
  if (k.trackedCount === 0) return { href: askHref("research", null), label: "Find competitors" };
  if (k.pendingQuestionCount > 0) return { href: askHref("confirm", null), label: "Confirm in chat" };
  if (k.needsEvidenceCount > 0) return { href: askHref("competitor", null), label: "Verify prices" };
  return { href: askHref("compare", null), label: "Compare my price" };
}

function discoveryNote(d: NonNullable<CiWorkspace["lastDiscovery"]>): string {
  if (d.status === "FAILED") return `The last search failed${d.failedReason ? ` (${d.failedReason.replace(/_/g, " ").toLowerCase()})` : ""}. That doesn’t mean there are no competitors.`;
  if (d.status === "PARTIAL") return "The last search was partial. More may exist.";
  return "The last search is fully decided.";
}

function Insights({ ws, subject }: { ws: CiWorkspace; subject: string | null }) {
  const items = ws.findings.slice(0, 6).map((f) => ({ key: f.id, text: findingText(f), href: askFindingHref(f.id, ws.selectedProductId, subject), meta: `${f.evidenceCount} screenshot${f.evidenceCount === 1 ? "" : "s"} behind it${f.sellerConfirmation === "CONFIRMED" ? " · confirmed by you" : ""}` }));
  if (items.length === 0) return <EmptyState compact title="No insights yet" description="They appear after verified screenshots." />;
  return (
    <ul className="ci-list ci-insights">
      {items.map((i) => (
        <li key={i.key} className="ci-change">
          <p className="ov-body" style={{ color: "var(--ov-ink)" }}>{i.text}</p>
          <p className="ov-meta">{i.meta}</p>
          <span><AskCeo href={i.href} label="Explain this" quiet /></span>
        </li>
      ))}
    </ul>
  );
}

function Activity({ ws, limit }: { ws: CiWorkspace; limit: number }) {
  if (ws.events.length === 0) return <EmptyState compact title="No activity yet" description="Screenshots, confirmations and alerts appear here." />;
  const days = groupEvents(ws.events).slice(0, limit);
  return (
    <ol className="ci-timeline" style={{ margin: 0, padding: 0, listStyle: "none" }} aria-label="Activity">
      {days.map((d) => (
        <li key={d.day} className="ci-day">
          <b>{dayLabel(d.day) ?? fmtDate(d.day)}</b>
          <ul>
            {d.items.map((i) => (
              <li key={i.label} className="ov-body" style={{ color: "var(--ov-ink)" }}>{i.label}{i.count > 1 ? ` × ${i.count}` : ""}</li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

/** Verified changes with a centred bar: a drop runs left, a rise runs right. The bar's length is a display scale of the backend's own percentage; the words say the same thing. */
function Changes({ ws }: { ws: CiWorkspace }) {
  const pct = (c: CiWorkspace["changes"][number]) => Math.abs(Number.parseFloat(c.deltaPct)) || 0;
  const max = Math.max(1, ...ws.changes.filter((c) => c.kind === "PRICE").map(pct));
  return (
    <ul className="ci-list">
      {ws.changes.map((c) => {
        const down = c.direction === "DECREASE";
        return (
          <li key={`${c.competitorId}-${c.occurredAt}`} className="ci-change">
            <div className="ov-card-head">
              <div style={{ minWidth: 0 }}>
                <div className="ov-title">
                  {c.label ?? "A competitor"}: {c.kind === "AVAILABILITY" ? `stock ${(c.availabilityChange ?? "changed").toLowerCase().replace(/_/g, " ")}` : `price ${down ? "down" : "up"} ${c.deltaPct.replace("-", "")}%`}
                </div>
                <div className="ov-meta">
                  {c.kind === "PRICE" ? `Change of ${formatPaise(c.deltaPaise)} · ` : ""}from the screenshot of {fmtDate(c.evidenceDate)}
                </div>
              </div>
              {c.kind === "PRICE" && <Pill tone={down ? "warn" : "good"}>{down ? "▼ Down" : "▲ Up"}</Pill>}
            </div>
            {c.kind === "PRICE" && (
              <div className="ci-diverge" aria-hidden>
                <i className={down ? "down" : "up"} style={{ width: `${(pct(c) / max) * 50}%` }} />
              </div>
            )}
            <span><AskCeo href={c.findingId ? askFindingHref(c.findingId, ws.selectedProductId, c.label) : askHref("competitor", c.label)} label="Explain this" quiet /></span>
          </li>
        );
      })}
    </ul>
  );
}

function CompetitorTable({ rows }: { rows: CiCompetitor[] }) {
  return (
    <div className="ci-table-wrap">
      <table className="ci-table" aria-label="Tracked competitors">
        <thead>
          <tr>
            <th scope="col">Competitor</th>
            <th scope="col">Price</th>
            <th scope="col">What a buyer pays</th>
            <th scope="col">Match</th>
            <th scope="col">Last evidence</th>
            <th scope="col">Status</th>
            {/* relative: the hidden text is absolutely positioned and must stay inside the table's scroll box, or it widens the page on phones */}
            <th scope="col" className="relative"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td data-label="Competitor">
                <div className="ci-name">{c.label ?? "Competitor"}</div>
                <div className="ci-sub">{c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase()}</div>
              </td>
              <td data-label="Price">
                {c.listedPricePaise !== null ? (
                  <>
                    <div className="ci-price">{formatPaise(c.listedPricePaise)}</div>
                    {c.deltaPct && <div className={`ci-delta ${c.deltaDirection === "DECREASE" ? "ci-delta--down" : "ci-delta--up"}`}>{c.deltaDirection === "DECREASE" ? "▼" : "▲"} {c.deltaPct.replace("-", "")}%</div>}
                  </>
                ) : (
                  <span className="ci-sub">{c.priceStatus === "UNVERIFIED" ? "Awaiting your confirmation" : "No current price"}</span>
                )}
              </td>
              <td data-label="What a buyer pays">
                {c.effectivePrice?.effective?.isAvailable ? (
                  <>
                    <div className="ci-price">{formatPaise(c.effectivePrice.effective.valuePaise)}<span className="ci-sub"> after discounts</span></div>
                    <div className="ci-sub">
                      {c.effectivePrice.buyerTotal?.isAvailable ? `${formatPaise(c.effectivePrice.buyerTotal.valuePaise)} with delivery` : `Total: ${unavailableWords(c.effectivePrice.buyerTotal?.unavailableReason)}`}
                    </div>
                    {offersLine(c.effectivePrice) && <div className="ci-sub">{offersLine(c.effectivePrice)}</div>}
                  </>
                ) : (
                  <span className="ci-sub">{c.effectivePrice?.effective ? unavailableWords(c.effectivePrice.effective.unavailableReason) : "Not available"}</span>
                )}
              </td>
              <td data-label="Match">
                {c.relevanceBand && c.relevanceScore !== null ? (
                  <span className="ci-match" title={c.relationshipClass !== "UNKNOWN" ? RELATIONSHIP_LABEL[c.relationshipClass] : undefined}>
                    <span className="ci-pips" aria-hidden>{[0, 1, 2].map((n) => <i key={n} className={n < ({ LOW: 1, MEDIUM: 2, HIGH: 3 } as Record<string, number>)[c.relevanceBand as string] ? "is-on" : undefined} />)}</span>
                    <span className="ci-name">{c.relevanceBand.charAt(0) + c.relevanceBand.slice(1).toLowerCase()}</span>
                  </span>
                ) : (
                  <span className="ci-sub">Not scored</span>
                )}
              </td>
              <td data-label="Last evidence">
                <div className="ci-name" style={{ fontWeight: 600 }}>{c.evidenceDate ? fmtDate(c.evidenceDate) : "No screenshot yet"}</div>
                <div className="ci-sub">{FRESHNESS_LABEL[c.freshness]}</div>
              </td>
              <td data-label="Status"><Pill tone={c.priceStatus === "VERIFIED" ? "good" : "warn"} icon={c.priceStatus === "VERIFIED" ? "check" : "alert"}>{PRICE_STATUS_LABEL[c.priceStatus]}</Pill></td>
              <td>
                <div className="ci-actions">
                  <AskCeo href={askHref("verify", c.label)} label={c.priceStatus === "VERIFIED" ? "Update price" : "Verify price"} variant="secondary" />
                  <AskCeo href={askHref("stop", c.label)} label="Stop tracking" quiet />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidateList({ rows }: { rows: CiCandidate[] }) {
  return (
    <ul className="ci-list">
      {rows.map((c) => (
        <li key={c.id} className="ci-item">
          <span className="ci-item-main">
            <span className="ov-title">
              {c.title ?? `${RELATIONSHIP_LABEL[c.relationshipClass]} on ${c.marketplace ? c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase() : "a marketplace"}`}
            </span>
            {c.title && (
              <span className="ov-meta">
                {c.marketplace ? c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase() : "A marketplace"} · {c.relationshipClass !== "UNKNOWN" ? RELATIONSHIP_LABEL[c.relationshipClass] : c.identityNote ?? "not classified yet"}
                {c.url && (<> · <a href={c.url} target="_blank" rel="noopener noreferrer" className="mt-focus pi-link">Open listing</a></>)}
              </span>
            )}
            <span className="ov-meta">
              {c.relevanceBand && c.relevanceScore !== null ? `Match: ${c.relevanceBand.charAt(0) + c.relevanceBand.slice(1).toLowerCase()}` : "Not scored"} · not verified yet
            </span>
          </span>
          <AskCeo href={askHref("trackone", c.title ?? "this competitor")} label="Track this" variant="secondary" />
        </li>
      ))}
    </ul>
  );
}

/** How far behind the newest screenshot one competitor's evidence is, in whole days, with its share of the longest gap. Dates only, no clock and no
 *  stale threshold (the page is not sent one); the Fresh / Getting old word beside it is the backend's call. Null when there is no dated evidence. */
function daysBehind(date: string | null | undefined, all: (string | null | undefined)[]): { days: number; share: number } | null {
  const t = (d: string | null | undefined) => (d ? Date.parse(d) : NaN);
  const times = all.map(t).filter((n) => Number.isFinite(n));
  const mine = t(date);
  if (times.length < 2 || !Number.isFinite(mine)) return null;
  const newest = Math.max(...times);
  const longest = newest - Math.min(...times);
  const day = 86_400_000;
  return { days: Math.round((newest - mine) / day), share: longest > 0 ? (newest - mine) / longest : 0 };
}
