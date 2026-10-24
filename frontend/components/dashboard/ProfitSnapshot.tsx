"use client";

import Link from "next/link";
import { PresentationView } from "@/components/ceo/hub/PresentationView";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState, Spinner } from "@/components/ui/LoadingState";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { HealthStrip } from "@/components/ceo/hub/HealthStrip";
import type { HealthEntry, PresentationFigure } from "@/lib/ceo";
import { actionLabel, asOfLabel } from "@/lib/ceoModel";
import type { HealthState } from "@/lib/useCeoHub";
import { daysSince, latestAsOf, STALE_AFTER_DAYS } from "@/lib/useBusinessHealth";

/** The Overview's profit block. Every word and number here is something `GET /api/v1/ceo/state/health` returned; nothing is computed, summed, rounded or
 * defaulted in the browser.
 *
 * Source of each part (backend/src/backend/ceo/business_state.py):
 *  - `BS_PNL_LATEST` is the latest persisted P&L period (engine results in `metric_result`). Its figures are labelled by the backend: "Net realized revenue",
 *    "Contribution profit", "Marketplace fees", each with a formatted value, a register (VERIFIED / DERIVED / ...), an as-of date and sometimes a note.
 *    The headline is the figure the backend calls "Contribution profit". If it is absent (nothing computed, or unavailable) there is no headline and the
 *    original strip is shown instead, with the backend's own gap text.
 *  - `BS_HEALTH_BANDS` is the CFO's GOOD / WATCH / AT-RISK bands over that same period; shown as the backend presented it.
 * There is no portfolio-level profit endpoint, so no trend, total or comparison is drawn. */
export const PNL_KEY = "BS_PNL_LATEST";
/** The backend's own label for the headline figure (`_PNL_METRICS` in business_state.py). Matching on it, not on position, keeps a reordered list safe. */
export const HEADLINE_LABEL = "Contribution profit";

const isNegative = (value: string) => /^[-−(]/.test(value.trim());
const statusText = (e: HealthEntry) => (e.status === "UNAVAILABLE" ? "Not available yet" : e.status.toLowerCase().replace(/_/g, " "));
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

/** One line saying how current the saved results are. The only place the Overview says it. */
function Freshness({ health, checkedAt }: { health: HealthState; checkedAt: string | null }) {
  const asOf = latestAsOf(health.entries);
  const age = daysSince(asOf);
  const stale = age !== null && age > STALE_AFTER_DAYS;
  const empty = health.entries.length === 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="data-freshness-badge">
        {health.status === "loading" && empty ? (
          <StatusBadge tone="neutral">Checking saved results…</StatusBadge>
        ) : health.status === "error" && empty ? (
          <StatusBadge tone="negative">Saved results unavailable</StatusBadge>
        ) : asOf ? (
          <StatusBadge tone={stale ? "warning" : "accent"} dot>{stale ? "Saved results are stale" : "Saved results are current"}</StatusBadge>
        ) : (
          <StatusBadge tone="neutral">No saved profit results yet</StatusBadge>
        )}
        {checkedAt && <span className="t-meta" style={{ color: "var(--text-5)" }}>Checked {clock(checkedAt)}</span>}
      </div>
      {(health.status === "loading" && empty) || asOf ? (
        <p className="t-meta m-0 max-w-[70ch]" style={{ color: "var(--text-5)" }} data-testid="data-freshness">
          {health.status === "loading" && empty
            ? "Checking your saved results…"
            : `Profit results shown are the latest saved ones, as of ${asOf!.slice(0, 10)}${age !== null ? ` (${age === 0 ? "today" : age === 1 ? "1 day ago" : `${age} days ago`})` : ""}.${stale ? " They may not reflect recent orders; upload newer reports in Profit & Finance to refresh them." : ""}`}
        </p>
      ) : null}
    </div>
  );
}

function Figure({ f, big = false }: { f: PresentationFigure; big?: boolean }) {
  const asOf = asOfLabel(f.as_of);
  return (
    <div data-testid="snapshot-figure" className="flex min-w-0 flex-col gap-1.5">
      <div className="t-label" style={{ color: "var(--text-5)" }}>{f.label}</div>
      <div data-testid="figure-value" className={big ? "t-metric-lg" : "t-headline"} style={{ color: isNegative(f.value) ? "var(--negative)" : "var(--text-1)", overflowWrap: "anywhere" }}>
        {f.value}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ProvenanceBadge register={f.register} />
        {asOf && <span className="t-meta" style={{ color: "var(--text-5)" }}>{asOf}</span>}
      </div>
      {f.note && <p className="t-meta m-0" style={{ color: "var(--text-5)" }}>{f.note}</p>}
    </div>
  );
}

function Headline({ entry, headline }: { entry: HealthEntry; headline: PresentationFigure }) {
  const p = entry.presentation!;
  const others = p.figures.filter((f) => f !== headline);
  const rest = { ...p, figures: [], offers: [] }; // facts, conflicts and gaps stay verbatim; the "you could also ask" chips are not actions on this page
  const hasRest = rest.facts.length > 0 || rest.gaps.length > 0 || (rest.conflicts?.length ?? 0) > 0 || (rest.artefacts?.length ?? 0) > 0;
  return (
    <div className="mt-panel mt-panel--elevated mt-surface--hero flex flex-col gap-5 rounded-2xl p-5 sm:p-6" data-testid="profit-hero" data-status={entry.status}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{actionLabel(entry.key)}</span>
        {entry.period && <span className="t-body-sm" style={{ color: "var(--text-4)" }}>{entry.period}</span>}
        {entry.status !== "COMPLETE" && <StatusBadge tone="neutral">{statusText(entry)}</StatusBadge>}
      </div>
      <Figure f={headline} big />
      {others.length > 0 && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-5 border-t pt-5 sm:grid-cols-2" style={{ borderColor: "var(--border-subtle)" }} data-testid="snapshot-others">
          {others.map((f) => <Figure key={`${f.ref.kind}-${f.ref.id}-${f.label}`} f={f} />)}
        </div>
      )}
      {hasRest && <PresentationView presentation={rest} compact />}
    </div>
  );
}

function OtherEntry({ entry }: { entry: HealthEntry }) {
  const asOf = asOfLabel(entry.asOf);
  return (
    <div className="mt-panel flex flex-col gap-3 rounded-2xl p-5" data-testid={`health-${entry.key}`} data-status={entry.status}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{actionLabel(entry.key)}</span>
        {entry.status !== "COMPLETE" && <StatusBadge tone="neutral">{statusText(entry)}</StatusBadge>}
        {entry.period && <span className="t-meta" style={{ color: "var(--text-5)" }}>{entry.period}</span>}
        {asOf && <span className="t-meta" style={{ color: "var(--text-5)" }}>{asOf}</span>}
      </div>
      {entry.presentation ? (
        <PresentationView presentation={{ ...entry.presentation, offers: [] }} compact />
      ) : (
        <p className="t-body-sm m-0" style={{ color: "var(--text-5)" }}>{entry.previewHint ?? "Nothing saved to show yet."}</p>
      )}
    </div>
  );
}

const linkBtn = "mt-btn mt-focus inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3.5 t-body font-semibold";

export function ProfitSnapshot({ health, onRefresh, refreshing, checkedAt }: { health: HealthState; onRefresh: () => void; refreshing: boolean; checkedAt: string | null }) {
  const empty = health.entries.length === 0;
  const pnl = health.entries.find((e) => e.key === PNL_KEY);
  const headline = pnl?.presentation?.figures.find((f) => f.label === HEADLINE_LABEL) ?? null;
  const others = health.entries.filter((e) => e !== pnl);
  const loading = health.status === "loading" && empty;

  // What to read next and where to act. With the headline and a second result it sits under that second result, which fills the column the headline leaves free.
  const footer = (
    <div className="flex flex-col gap-3" data-testid="snapshot-footer">
      {!empty && (
        <p className="t-meta m-0 max-w-[70ch]" style={{ color: "var(--text-6)" }}>
          Each result is one saved calculation with its own period and source. A single combined profit trend is not available yet.
        </p>
      )}
      <div className="flex flex-wrap gap-2.5">
        {!empty && <Link href="/dashboard/cfo#import" className={linkBtn} style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}>Upload reports</Link>}
        <Link href="/dashboard/ceo-hub" className={linkBtn} style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}>
          Ask where profit is leaking <Icon name="arrow" size={12} strokeWidth={1.9} />
        </Link>
        <Link href="/dashboard/cfo#profitability" className={linkBtn} style={{ color: "var(--text-3)", border: "1px solid var(--border-hover)" }}>
          Open Profit &amp; Finance <Icon name="arrow" size={12} strokeWidth={1.9} />
        </Link>
      </div>
    </div>
  );

  return (
    <Section
      title="Profit snapshot"
      panel={false}
      action={
        <>
          {!loading && (
            <button type="button" onClick={onRefresh} disabled={refreshing} className="mt-btn mt-focus min-h-10 rounded-lg px-3 t-body-sm font-semibold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
              {refreshing ? <span className="inline-flex items-center gap-2"><Spinner size={12} /> Refreshing…</span> : "Refresh"}
            </button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Freshness health={health} checkedAt={checkedAt} />
        {health.status === "error" && !empty && (
          <ErrorNotice message="Could not refresh your saved results. Showing the last ones that loaded." onRetry={onRefresh} />
        )}
        {loading ? (
          <div className="mt-panel rounded-2xl p-5 sm:p-6" data-testid="health-loading">
            <LoadingState lines={4} label="Loading your saved results" />
          </div>
        ) : empty && health.status === "error" ? (
          <div data-testid="health-unavailable">
            <ErrorNotice message="Your saved results could not be loaded, so this page cannot say whether any exist. Try again in a moment." onRetry={onRefresh} />
          </div>
        ) : empty ? (
          <div className="mt-panel rounded-2xl" data-testid="health-none-saved">
            <EmptyState
              icon="finance"
              title="Nothing saved yet"
              description="Your latest profit appears here after you upload your reports in Profit & Finance."
              action={<Link href="/dashboard/cfo#import" className={linkBtn} style={{ color: "var(--text-2)", border: "1px solid var(--border-hover)" }}>Upload reports</Link>}
            />
          </div>
        ) : pnl && headline ? (
          <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-12">
            <div className={others.length > 0 ? "xl:col-span-7" : "xl:col-span-12"}><Headline entry={pnl} headline={headline} /></div>
            {others.length > 0 && (
              <div className="flex flex-col gap-4 xl:col-span-5">
                {others.map((e) => <OtherEntry key={e.key} entry={e} />)}
                {footer}
              </div>
            )}
          </div>
        ) : (
          <HealthStrip health={health} onRefresh={onRefresh} refreshing={refreshing} />
        )}
        {(empty || !(pnl && headline && others.length > 0)) && footer}
      </div>
    </Section>
  );
}
