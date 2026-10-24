"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { ApiError, type MarketOverview, type MetricResult } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import {
  askFindingHref, askHref, eventLabel, groupEvents, findingText, fmtDate, fmtDateTime, FRESHNESS_LABEL, offersLine, PRICE_STATUS_LABEL, productLabel, RELATIONSHIP_LABEL, themeList, unavailableWords,
  type CiCandidate, type CiCompetitor, type CiWorkspace,
} from "@/lib/ciWorkspace";
import { formatPaise } from "@/lib/piShowcase";

/** The read-only Competitor Intelligence dashboard (docs/specs/competitor-intelligence-agent.md §6.29).
 * It shows what CEO-CI investigations already produced. There is no form, no input, no upload and no control that changes data: the buttons switch what is shown, and every
 * action is a link into the CEO Hub (the only place the seller asks, uploads or confirms). Every figure is stored by the backend or the engine; a missing value says so and why. */

export type CiClient = {
  workspace(productId: string | null): Promise<CiWorkspace>;
  market(productId: string): Promise<MarketOverview>;
};

const card = { background: "var(--bg-card)", border: "1px solid var(--border-subtle)" } as const;
const panel = { background: "var(--bg-card)", border: "1px solid var(--accent-border-subtle)" } as const;

function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "accent" | "neutral" | "warn" }) {
  const color = tone === "accent" ? "var(--accent)" : tone === "warn" ? "var(--warning)" : "var(--text-5)";
  return (
    <span className="t-micro inline-block whitespace-nowrap rounded px-1.5 py-0.5 font-bold uppercase" style={{ color, border: `1px solid ${color}` }}>
      {children}
    </span>
  );
}

/** A link into the CEO Hub. Three levels so one view has one strong action: `primary` is the single next step (solid green), `secondary` is a visible but calm action
 * (a bordered button), and `quiet` is for the rest (a lighter border). `quiet` as a flag is the same as `variant="quiet"`. */
function AskCeo({ href, label, quiet = false, variant }: { href: string; label: string; quiet?: boolean; variant?: "primary" | "secondary" | "quiet" }) {
  const level = variant ?? (quiet ? "quiet" : "primary");
  const style =
    level === "primary"
      ? { background: "var(--accent)", color: "var(--accent-on-fill)" }
      : level === "secondary"
        ? { border: "1px solid var(--border-hover)", color: "var(--text-2)" }
        : { border: "1px solid var(--border-default)", color: "var(--text-3)" };
  return (
    <Link href={href} className="mt-btn mt-focus inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-3 t-meta font-bold" style={style}>
      {label}
    </Link>
  );
}

function Kpi({ label, value, hint, tone }: { label: string; value: string | number | null; hint: ReactNode; tone?: "warn" }) {
  return (
    <div className="rounded-xl p-4" style={card}>
      <div className="t-label" style={{ color: "var(--text-5)" }}>{label}</div>
      <div className="mt-2 t-headline font-semibold" style={{ color: value === null ? "var(--text-6)" : tone === "warn" ? "var(--warning)" : "var(--text-1)" }}>
        {value === null ? "Not available" : value}
      </div>
      <div className="mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{hint}</div>
    </div>
  );
}

function Box({ title, subtitle, children, action }: { title: string; subtitle?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl p-4" style={card}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{title}</h2>
          {subtitle && <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

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
        setCheckedAt(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
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

  return (
    <div className="mt-content flex flex-col gap-6" data-testid="ci-dashboard">
      {/* header: which product, and the two CEO shortcuts */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Product shown">
          {ws.products.length === 0 ? (
            <span className="t-body-sm" style={{ color: "var(--text-6)" }}>No products yet</span>
          ) : (
            ws.products.map((p) => (
              <button
                key={p.productId}
                type="button"
                aria-pressed={p.productId === (pending?.kind === "switch" ? pending.productId : ws.selectedProductId)}
                aria-busy={pending?.kind === "switch" && pending.productId === p.productId}
                onClick={() => {
                  // The product on screen, or the one already being loaded, needs no second request.
                  if (p.productId === ws.selectedProductId && !pending) return;
                  if (pending?.kind === "switch" && pending.productId === p.productId) return;
                  void load(p.productId, "switch");
                }}
                className="mt-focus min-h-10 rounded-full px-3.5 t-meta font-bold"
                style={{
                  color: p.productId === (pending?.kind === "switch" ? pending.productId : ws.selectedProductId) ? "var(--accent)" : "var(--text-3)",
                  background: p.productId === (pending?.kind === "switch" ? pending.productId : ws.selectedProductId) ? "var(--accent-fill-default)" : "var(--fill-hover)",
                  border: `1px solid ${p.productId === (pending?.kind === "switch" ? pending.productId : ws.selectedProductId) ? "var(--accent-border-strong)" : "var(--border-default)"}`,
                }}
              >
                {productLabel(p)}
              </button>
            ))
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={askHref("research", null)} className="mt-btn mt-focus inline-flex min-h-10 items-center rounded-lg px-4 t-body-sm font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
            Find competitors
          </Link>
          <Link href={askHref("track", null)} className="mt-btn mt-focus inline-flex min-h-10 items-center rounded-lg px-4 t-body-sm font-bold" style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}>
            Track a competitor
          </Link>
        </div>
      </div>

      {/* where this data comes from: which product, as of when, and whether it is being replaced right now */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="ci-context">
        <p role="status" className="m-0 t-meta" style={{ color: "var(--text-5)" }}>
          {pending?.kind === "switch"
            ? `Loading ${ws.products.find((p) => p.productId === pending.productId)?.title ?? "the next product"}… the ${subject ?? "tracked competitors"} view below is the previous one.`
            : pending?.kind === "refresh"
              ? "Refreshing… what is shown is the last result that loaded."
              : `Showing ${subject ?? "all tracked competitors"} · Data as of ${fmtDateTime(ws.asOf)}${checkedAt ? ` · checked ${checkedAt}` : ""}`}
        </p>
        <button
          type="button"
          onClick={() => void load(ws.selectedProductId, "refresh")}
          disabled={pending !== null}
          className="mt-btn mt-btn-secondary mt-focus inline-flex min-h-[40px] items-center gap-2 rounded-lg px-3 py-1 t-meta font-bold disabled:cursor-not-allowed"
          style={{ opacity: pending ? 0.7 : 1 }}
        >
          {pending?.kind === "refresh" && <Spinner size={12} />}
          {pending?.kind === "refresh" ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {failure && (
        <ErrorNotice
          message={`${failure.message} ${failure.kind === "switch" ? `Still showing ${subject ?? "the previous view"}.` : "What is shown may be out of date."}`}
          onRetry={() => void load(failure.productId, failure.kind)}
        />
      )}

      <div className="flex flex-col gap-6 transition-opacity" style={{ opacity: pending ? 0.6 : 1 }} aria-busy={pending !== null}>
      {/* the CEO's next step: plain facts from the counts above, one link into the conversation */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl p-4" style={panel}>
        <div>
          <div className="t-body font-semibold" style={{ color: "var(--text-2)" }}>What to do next</div>
          <p className="mt-0.5 t-body-sm" style={{ color: "var(--text-5)" }}>{nextStep(ws)}</p>
        </div>
        {(() => {
          const act = nextAction(ws);
          return <AskCeo href={act.href} label={act.label} />;
        })()}
      </div>

      {/* nothing yet: a calm explanation, never sample data */}
      {k.trackedCount === 0 && ws.candidates.length === 0 ? (
        <div className="rounded-xl" style={panel}>
          <EmptyState
            icon="competitors"
            title="No competitors tracked yet"
            description="Competitor Intelligence finds rivals for your products, reads the screenshots you send, and shows what changed. It all starts in a conversation with the CEO. Nothing here is estimated or sample data."
            action={<AskCeo href={askHref("research", subject)} label="Find competitors" variant="secondary" />}
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi label="Competitors tracked" value={ws.watchlist ? `${ws.watchlist.used} of ${ws.watchlist.limit}` : k.trackedCount} hint={ws.watchlist && ws.watchlist.free === 0 ? "List is full: stop tracking one to add another" : `${k.verifiedCount} with a verified price`} />
          <Kpi
            label="Need fresh evidence"
            value={k.needsEvidenceCount}
            tone={k.needsEvidenceCount > 0 ? "warn" : undefined}
            hint={k.needsEvidenceCount > 0 ? "Send the CEO a new screenshot" : "All evidence is recent"}
          />
          <Kpi label="Verified changes" value={k.importantChangeCount} hint="Price or stock, from confirmed screenshots" />
          <Kpi label="Customer insights" value={k.reviewInsightCount} hint="From review screenshots you sent" />
        </div>
      )}

      {(k.trackedCount > 0 || ws.candidates.length > 0) && (
        <>
      <section aria-labelledby="ci-sec-competitors" className="flex flex-col gap-3">
        <div><h2 id="ci-sec-competitors" className="t-headline font-semibold" style={{ color: "var(--text-1)" }}>Your competitors</h2><p className="t-meta-sm" style={{ color: "var(--text-6)" }}>Who you track, their verified price, and the ones waiting for your decision.</p></div>
        <div className="flex flex-col gap-4">
          <Box title="Tracked competitors" subtitle="Relevance is shown with its score, never as a bare badge.">
            {ws.competitors.length === 0 ? (
              <EmptyState compact title="No competitors tracked for this product" description="Ask the CEO to find some, or tell it a marketplace link to track." action={<AskCeo href={askHref("research", subject)} label="Find competitors" />} />
            ) : (
              <CompetitorTable rows={ws.competitors} productId={ws.selectedProductId} />
            )}
          </Box>
          <Box title="Found, awaiting your decision" subtitle="Search leads. They are not verified prices; approving one asks you for a screenshot.">
            {ws.candidates.length === 0 ? (
              <EmptyState compact title="No candidates waiting" description={ws.lastDiscovery ? discoveryNote(ws.lastDiscovery) : "No competitor search has run for this product yet."} />
            ) : (
              <CandidateList rows={ws.candidates} subject={subject} />
            )}
          </Box>
        </div>
      </section>

      <section aria-labelledby="ci-sec-overview" className="flex flex-col gap-3">
        <div><h2 id="ci-sec-overview" className="t-headline font-semibold" style={{ color: "var(--text-1)" }}>Where your price stands</h2><p className="t-meta-sm" style={{ color: "var(--text-6)" }}>Your price against what competitors charge, and what to do next.</p></div>
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Box title="Where your price sits" subtitle="The band is computed by Metrion's price engine from your verified competitor prices. Nothing is estimated.">
              {ws.selectedProductId?.startsWith("category:") ? (
                <EmptyState
                  compact
                  title="Compare your price with these competitors"
                  description="These competitors are tracked for a category, not for one of your products. Tell the CEO your selling price and it compares it with every competitor that has a verified price."
                  action={<AskCeo href={askHref("compare", null)} label="Compare my price" variant="secondary" />}
                />
              ) : marketLoading ? (
                <LoadingState lines={2} label="Loading the price band" />
              ) : bandAvailable && market ? (
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[["Q1", "Q1"], ["Q3", "Q3"], ["Typical low", "TYPICAL_LOW"], ["Typical high", "TYPICAL_HIGH"]].map(([label, key]) => (
                    <div key={key}>
                      <dt className="t-meta-sm" style={{ color: "var(--text-6)" }}>{label}</dt>
                      <dd className="t-body font-semibold" style={{ color: "var(--text-1)" }}>{formatPaise(bandRow(market.rows, key)?.valuePaise)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <EmptyState
                  compact
                  title="No price band yet"
                  description={
                    marketNote ??
                    (market && market.rows[0]?.unavailableReason
                      ? `${market.rows[0].unavailableReason}. A band needs at least ${market.minCompetitorsRequired} competitors with a verified price.`
                      : "A band needs a few competitors with a verified price. Send the CEO their listing screenshots.")
                  }
                />
              )}
              {verifiedPrices.length > 0 && (
                <ul className="mt-4 flex flex-wrap gap-2" aria-label="Verified competitor prices">
                  {verifiedPrices.map((c) => (
                    <li key={c.id} className="rounded-lg px-2.5 py-1 t-meta" style={{ background: "var(--fill-hover)", color: "var(--text-3)" }}>
                      {c.label ?? "Competitor"} · {formatPaise(c.listedPricePaise)}
                    </li>
                  ))}
                </ul>
              )}
            </Box>
          </div>
          <Box title="Insights and next steps" subtitle="Each one rests on evidence you sent.">
            <Insights ws={ws} subject={subject} />
          </Box>
        </div>
      </section>

      <section aria-labelledby="ci-sec-changes" className="flex flex-col gap-3">
        <div><h2 id="ci-sec-changes" className="t-headline font-semibold" style={{ color: "var(--text-1)" }}>What changed</h2><p className="t-meta-sm" style={{ color: "var(--text-6)" }}>Price and stock moves from the screenshots you confirmed.</p></div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Box title="Verified changes" subtitle="Only confirmed, recent screenshots count. Competitors are not watched between your screenshots.">
            {ws.changes.length === 0 ? (
              <EmptyState compact title="No verified changes yet" description="A change appears after you send a second screenshot of a competitor and confirm its price." />
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {ws.changes.map((c) => (
                  <li key={`${c.competitorId}-${c.occurredAt}`} className="rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
                    <div className="t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>
                      {c.label ?? "A competitor"}: {c.kind === "AVAILABILITY" ? `stock ${(c.availabilityChange ?? "changed").toLowerCase().replace(/_/g, " ")}` : `price ${c.direction === "DECREASE" ? "down" : "up"} ${c.deltaPct.replace("-", "")}%`}
                    </div>
                    <div className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>
                      {c.kind === "PRICE" ? `Change of ${formatPaise(c.deltaPaise)} · ` : ""}from the screenshot of {fmtDate(c.evidenceDate)}
                    </div>
                    <div className="mt-2"><AskCeo href={c.findingId ? askFindingHref(c.findingId, ws.selectedProductId, c.label) : askHref("competitor", c.label)} label="Explain this" quiet /></div>
                  </li>
                ))}
              </ul>
            )}
          </Box>
          <Box title="Freshness" subtitle="How recent the evidence behind each competitor is.">
            {ws.competitors.length === 0 ? (
              <EmptyState compact title="Nothing to check yet" description="Freshness appears once a competitor is tracked." />
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {ws.competitors.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3 t-body-sm">
                    <span style={{ color: "var(--text-3)" }}>{c.label ?? "Competitor"}</span>
                    <span className="flex items-center gap-2">
                      <span style={{ color: "var(--text-6)" }}>{c.evidenceDate ? fmtDate(c.evidenceDate) : "no screenshot yet"}</span>
                      <Badge tone={c.freshness === "FRESH" ? "accent" : "warn"}>{FRESHNESS_LABEL[c.freshness]}</Badge>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Box>
        </div>
      </section>

      <section aria-labelledby="ci-sec-evidence" className="flex flex-col gap-3">
        <div><h2 id="ci-sec-evidence" className="t-headline font-semibold" style={{ color: "var(--text-1)" }}>Evidence and reviews</h2><p className="t-meta-sm" style={{ color: "var(--text-6)" }}>What is waiting for your confirmation, what customers say, and the full history.</p></div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Box title="Waiting on you" subtitle="Details the CEO asked you to confirm.">
            {ws.pendingConfirmations.length === 0 ? (
              <EmptyState compact title="Nothing waiting" description="When a screenshot shows a price or stock detail that needs your confirmation, it is listed here until you answer the CEO." />
            ) : (
              <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {ws.pendingConfirmations.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3 rounded-lg p-3 t-body-sm" style={{ background: "var(--fill-hover)" }}>
                    <span style={{ color: "var(--text-3)" }}>Confirm the {p.field.replace(/_paise$/, "").replace(/_/g, " ")}</span>
                    <span className="flex items-center gap-2"><span style={{ color: "var(--text-6)" }}>until {fmtDate(p.expiresAt)}</span><AskCeo href={askHref("confirm", null)} label="Confirm in chat" quiet /></span>
                  </li>
                ))}
              </ul>
            )}
          </Box>
          <Box title="Review insights" subtitle="Recurring themes from review screenshots you sent, with how many reviews were read.">
            {ws.reviewInsights.length === 0 ? (
              <EmptyState compact title="No review insights yet" description="Send the CEO a screenshot of a competitor's reviews and ask what customers complain about." action={<AskCeo href={askHref("reviews", null)} label="Ask about reviews" />} />
            ) : (
              <ul className="m-0 flex list-none flex-col gap-3 p-0">
                {ws.reviewInsights.map((r) => (
                  <li key={r.competitorId} className="rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
                    <div className="t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>{r.label ?? "A competitor"}</div>
                    <div className="mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>
                      {r.reviewsConsidered ? `${r.reviewsConsidered} reviews read` : "Sample size not stated"} · {fmtDate(r.evidenceDate)} · confidence {r.confidence.toLowerCase()}
                    </div>
                    {themeList(r.complaintThemes).length > 0 && <div className="mt-1 t-body-sm" style={{ color: "var(--text-3)" }}>Complaints: {themeList(r.complaintThemes).join(", ")}</div>}
                    {themeList(r.positiveThemes).length > 0 && <div className="mt-0.5 t-body-sm" style={{ color: "var(--text-3)" }}>Praised: {themeList(r.positiveThemes).join(", ")}</div>}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <AskCeo href={askHref("reviewsfor", r.label)} label="Add more reviews" quiet />
                      {r.findingId && <AskCeo href={askFindingHref(r.findingId, ws.selectedProductId, r.label)} label="Explain this" quiet />}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Box>
          <div className="lg:col-span-2">
            <Box title="History" subtitle="Every evidence, approval and alert decision, in order.">
              <Activity ws={ws} limit={40} />
            </Box>
          </div>
        </div>
      </section>
        </>
      )}
      </div>
    </div>
  );
}

function nextStep(ws: CiWorkspace): string {
  const k = ws.kpis;
  if (k.trackedCount === 0) return "No competitors are tracked yet. Find some, tick the ones to track, and they appear here.";
  if (k.pendingQuestionCount > 0) return `${k.pendingQuestionCount} detail${k.pendingQuestionCount === 1 ? "" : "s"} from your screenshots ${k.pendingQuestionCount === 1 ? "is" : "are"} waiting for your confirmation.`;
  if (k.needsEvidenceCount > 0) return `${k.needsEvidenceCount} competitor${k.needsEvidenceCount === 1 ? "" : "s"} ${k.needsEvidenceCount === 1 ? "has" : "have"} no recent screenshot. Send the CEO fresh ones so the comparison is current.`;
  return "Your evidence is current. Compare your price with them, or add a reviews screenshot to see what customers say.";
}

function nextAction(ws: CiWorkspace): { href: string; label: string } {
  const k = ws.kpis;
  if (k.trackedCount === 0) return { href: askHref("research", null), label: "Find competitors" };
  if (k.pendingQuestionCount > 0) return { href: askHref("confirm", null), label: "Confirm in chat" };
  if (k.needsEvidenceCount > 0) return { href: askHref("competitor", null), label: "Verify prices" };
  return { href: askHref("compare", null), label: "Compare my price" };
}

function discoveryNote(d: NonNullable<CiWorkspace["lastDiscovery"]>): string {
  if (d.status === "FAILED") return `The last search did not complete${d.failedReason ? ` (${d.failedReason.replace(/_/g, " ").toLowerCase()})` : ""}. Nothing was found, which is not the same as no competitors existing.`;
  if (d.status === "PARTIAL") return "The last search only partly completed, so more competitors may exist.";
  return "The last search finished and everything it found has been decided on.";
}

function Insights({ ws, subject }: { ws: CiWorkspace; subject: string | null }) {
  const items = ws.findings.slice(0, 6).map((f) => ({ key: f.id, text: findingText(f), href: askFindingHref(f.id, ws.selectedProductId, subject), meta: `${f.evidenceCount} screenshot${f.evidenceCount === 1 ? "" : "s"} behind it${f.sellerConfirmation === "CONFIRMED" ? " · confirmed by you" : ""}` }));
  if (items.length === 0) return <EmptyState compact title="No insights yet" description="Insights appear once the CEO has verified screenshots to work from." />;
  return (
    <ul className="m-0 flex list-none flex-col gap-3 p-0">
      {items.map((i) => (
        <li key={i.key} className="rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
          <p className="t-body-sm" style={{ color: "var(--text-3)" }}>{i.text}</p>
          <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{i.meta}</p>
          <div className="mt-2"><AskCeo href={i.href} label="Explain this" quiet /></div>
        </li>
      ))}
    </ul>
  );
}

function Activity({ ws, limit }: { ws: CiWorkspace; limit: number }) {
  if (ws.events.length === 0) return <EmptyState compact title="No activity yet" description="Screenshots, confirmations and alerts about your competitors are recorded here." />;
  const days = groupEvents(ws.events).slice(0, limit);
  return (
    <ol className="m-0 flex list-none flex-col gap-3 p-0" aria-label="Activity">
      {days.map((d) => (
        <li key={d.day}>
          <div className="t-meta font-bold" style={{ color: "var(--text-4)" }}>{fmtDate(d.day)}</div>
          <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0">
            {d.items.map((i) => (
              <li key={i.label} className="t-body-sm" style={{ color: "var(--text-3)" }}>{i.label}{i.count > 1 ? ` × ${i.count}` : ""}</li>
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

function CompetitorTable({ rows, productId }: { rows: CiCompetitor[]; productId: string | null }) {
  return (
    <div className="mt-table-wrap">
      <table className="mt-table" aria-label="Tracked competitors">
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
              <td>
                <div className="font-semibold" style={{ color: "var(--text-2)" }}>{c.label ?? "Competitor"}</div>
                <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase()}</div>
              </td>
              <td>
                {c.listedPricePaise !== null ? (
                  <>
                    <div style={{ color: "var(--text-1)" }}>{formatPaise(c.listedPricePaise)}</div>
                    {c.deltaPct && <div className="t-meta-sm" style={{ color: c.deltaDirection === "DECREASE" ? "var(--negative)" : "var(--text-5)" }}>{c.deltaDirection === "DECREASE" ? "▼" : "▲"} {c.deltaPct.replace("-", "")}%</div>}
                  </>
                ) : (
                  <span style={{ color: "var(--text-6)" }}>{c.priceStatus === "UNVERIFIED" ? "Awaiting your confirmation" : "No current price"}</span>
                )}
              </td>
              <td>
                {c.effectivePrice?.effective?.isAvailable ? (
                  <>
                    <div style={{ color: "var(--text-1)" }}>{formatPaise(c.effectivePrice.effective.valuePaise)}<span className="t-meta-sm" style={{ color: "var(--text-6)" }}> after discounts</span></div>
                    <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>
                      {c.effectivePrice.buyerTotal?.isAvailable ? `${formatPaise(c.effectivePrice.buyerTotal.valuePaise)} with delivery` : `Total: ${unavailableWords(c.effectivePrice.buyerTotal?.unavailableReason)}`}
                    </div>
                    {offersLine(c.effectivePrice) && <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{offersLine(c.effectivePrice)}</div>}
                  </>
                ) : (
                  <span style={{ color: "var(--text-6)" }}>{c.effectivePrice?.effective ? unavailableWords(c.effectivePrice.effective.unavailableReason) : "Not available"}</span>
                )}
              </td>
              <td>
                {c.relevanceBand && c.relevanceScore !== null ? (
                  <span style={{ color: "var(--text-3)" }} title={c.relationshipClass !== "UNKNOWN" ? RELATIONSHIP_LABEL[c.relationshipClass] : undefined}>{c.relevanceBand.charAt(0) + c.relevanceBand.slice(1).toLowerCase()}</span>
                ) : (
                  <span style={{ color: "var(--text-6)" }}>Not scored</span>
                )}
              </td>
              <td>
                <div style={{ color: "var(--text-3)" }}>{c.evidenceDate ? fmtDate(c.evidenceDate) : "No screenshot yet"}</div>
                <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{FRESHNESS_LABEL[c.freshness]}</div>
              </td>
              <td><Badge tone={c.priceStatus === "VERIFIED" ? "accent" : "warn"}>{PRICE_STATUS_LABEL[c.priceStatus]}</Badge></td>
              <td>
                <div className="flex flex-wrap gap-2">
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

function CandidateList({ rows, subject }: { rows: CiCandidate[]; subject: string | null }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0">
      {rows.map((c) => (
        <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
          <div>
            <div className="t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>
              {c.title ?? `${RELATIONSHIP_LABEL[c.relationshipClass]} on ${c.marketplace ? c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase() : "a marketplace"}`}
            </div>
            {c.title && (
              <div className="mt-0.5 t-meta-sm" style={{ color: "var(--text-5)" }}>
                {c.marketplace ? c.marketplace.charAt(0) + c.marketplace.slice(1).toLowerCase() : "A marketplace"} · {c.relationshipClass !== "UNKNOWN" ? RELATIONSHIP_LABEL[c.relationshipClass] : c.identityNote ?? "not classified yet"}
                {c.url && (<> · <a href={c.url} target="_blank" rel="noopener noreferrer" className="mt-focus underline" style={{ color: "var(--text-3)" }}>Open listing</a></>)}
              </div>
            )}
            <div className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>
              {c.relevanceBand && c.relevanceScore !== null ? `Match: ${c.relevanceBand.charAt(0) + c.relevanceBand.slice(1).toLowerCase()}` : "Not scored"} · not verified yet
            </div>
          </div>
          <AskCeo href={askHref("trackone", c.title ?? "this competitor")} label="Track this" variant="secondary" />
        </li>
      ))}
    </ul>
  );
}
