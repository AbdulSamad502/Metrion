"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import { ChoiceChips, ProblemNotice, SubmitButton, Unit, useAction, when } from "@/components/cmo/shared";
import { useCmoSession } from "@/components/cmo/session";
import {
  cmo, explainCmoError, MARKETPLACES, marketplaceLabel, type CmoProblem, type TrendFinding, type TrendListItem, type TrendPreview, type TrendReport, type TrendRun,
  type TrendSectionData,
} from "@/lib/cmo";

const SECTION_ORDER = ["NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT"] as const;
const SECTION_TITLE: Record<string, string> = {
  NICHE: "1 · Your niche",
  MARKET_NEWS: "2 · Marketplace and e-commerce news",
  REPORTED_TACTICS: "3 · Reported tactics",
  NEW_PRODUCTS_BUZZ: "4 · New products and buzz",
  ADJACENT: "5 · Adjacent opportunities",
};
const SECTION_HINT: Record<string, string> = {
  NICHE: "Signals related to your confirmed niche terms. Attention in a source is not demand or sales.",
  MARKET_NEWS: "Dated policy, fee, seller-program and seasonal updates.",
  REPORTED_TACTICS: "Approaches that others report. Not verified by Metrion, and not advice.",
  NEW_PRODUCTS_BUZZ: "Launches and emerging themes. An attention signal is not proof of sales.",
  ADJACENT: "Related categories worth investigating — not ranked, sized or called winners.",
};
const SECTION_CHIPS = SECTION_ORDER.map((id) => ({ id, label: SECTION_TITLE[id].slice(4) }));

const STATE_TONE: Record<string, Tone> = { COMPLETE: "accent", PARTIAL: "warning", UNAVAILABLE: "neutral" };
const STATE_LABEL: Record<string, string> = { COMPLETE: "Found", PARTIAL: "Partly found", UNAVAILABLE: "Not available" };
const CORROBORATION: Record<string, { label: string; tone: Tone }> = {
  SINGLE_SOURCE: { label: "One source", tone: "neutral" }, WEAK: { label: "Few sources", tone: "warning" }, MODERATE: { label: "Several sources", tone: "info" }, STRONG: { label: "Many independent sources", tone: "accent" },
};
const RECENCY: Record<string, string> = { FRESH: "Very recent", RECENT: "Recent", OLDER: "Older", DATE_UNKNOWN: "Date unknown" };

export function TrendsTab() {
  const { getToken } = useAuth();
  const s = useCmoSession();
  const [sections, setSections] = useState<string[]>([...SECTION_ORDER]);
  const preview = useAction<TrendPreview>();
  const run = useAction<TrendRun>();
  const [shown, setShown] = useState<TrendRun | null>(null);
  const [history, setHistory] = useState<TrendListItem[] | null>(null);
  const [historyProblem, setHistoryProblem] = useState<CmoProblem | null>(null);
  const [openProblem, setOpenProblem] = useState<CmoProblem | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setHistory((await cmo.trendList(getToken)).reports);
      setHistoryProblem(null);
    } catch (e) {
      setHistoryProblem(explainCmoError(e));
    }
  }, [getToken]);
  useEffect(() => {
    (async () => {
      await loadHistory();
    })();
  }, [loadHistory]);

  const doPreview = async () => {
    setShown(null);
    run.reset();
    await preview.run(() => cmo.trendPreview(getToken, sections, s.marketplaces));
  };
  const doRun = async () => {
    const p = preview.result;
    if (!p) return;
    const slot = `trends-${p.digest.slice(0, 16)}`; // one key per previewed plan: a retry or double click is a replay, never a second report
    const r = await run.run(() => cmo.trendRun(getToken, s.keyFor(slot), p.digest, sections, s.marketplaces));
    if (r) {
      setShown(r);
      s.record("Market trend report", r.unitsBilled.cmo, r.unitsBilled.shared);
      await loadHistory();
    }
  };
  const open = async (id: string) => {
    setOpenProblem(null);
    try {
      setShown(await cmo.trendGet(getToken, id));
    } catch (e) {
      setOpenProblem(explainCmoError(e));
    }
  };

  const p = preview.result;
  const planChanged = run.problem?.kind === "changed";

  return (
    <div className="mt-stack">
      <Section title="Market trends" hint="Research what is being reported about your niche and your marketplaces. You see the exact searches first; nothing is sent until you press the button.">
        <div className="flex flex-col gap-3">
          <ChoiceChips options={SECTION_CHIPS} value={sections} onChange={setSections} label="Sections to research" />
          <div className="t-meta" style={{ color: "var(--text-6)" }}>
            Marketplaces for the news and tactics searches: {s.marketplaces.length ? s.marketplaces.map(marketplaceLabel).join(", ") : MARKETPLACES.map((m) => m.label).join(", ")}. A report costs one CMO unit plus one market-research unit, only if it succeeds.
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <SubmitButton primary={!p} onClick={doPreview} busy={preview.busy} label={p ? "Refresh the preview" : "Show me the searches"} busyLabel="Preparing…" disabled={sections.length === 0} />
          </div>
          <ProblemNotice problem={preview.problem} onRetry={doPreview} />
          {preview.busy && <LoadingState lines={3} label="Preparing the preview" />}
        </div>
      </Section>

      {p && !preview.busy && (
        <Section title="Exactly what will be sent" hint={p.notice}>
          <div className="mt-table-wrap">
            <table className="mt-table">
              <caption className="sr-only">Searches that will be sent to the search providers</caption>
              <thead>
                <tr><th scope="col">Section</th><th scope="col">Provider</th><th scope="col">Search text</th></tr>
              </thead>
              <tbody>
                {p.queries.map((q) => (
                  <tr key={q.queryId}>
                    <td>{SECTION_TITLE[q.section]?.slice(4) ?? q.section}</td>
                    <td>{q.provider === "TAVILY" ? "Web news search" : "Video search"}</td>
                    <td className="break-words">{q.query}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {p.queries.length === 0 && <EmptyState compact title="Nothing to send" description="Every chosen section needs a confirmed niche term first." />}
          {Object.keys(p.unavailableSections).length > 0 && (
            <ul className="mt-3 flex flex-col gap-1">
              {Object.entries(p.unavailableSections).map(([k, why]) => (
                <li key={k} className="t-body-sm" style={{ color: "var(--warning)" }}>
                  {SECTION_TITLE[k]?.slice(4) ?? k}: {why}
                </li>
              ))}
            </ul>
          )}
          {p.unresearchedTerms.length > 0 && (
            <div className="mt-2 t-body-sm" style={{ color: "var(--text-5)" }}>
              Not researched this time (search limit): {p.unresearchedTerms.join(", ")}.
            </div>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <SubmitButton primary onClick={doRun} busy={run.busy} label="Send these searches and build the report" busyLabel="Researching… this can take a minute" disabled={p.queries.length === 0} />
            {planChanged && <SubmitButton onClick={doPreview} busy={preview.busy} label="Review the new preview" busyLabel="Preparing…" />}
          </div>
          <div className="mt-3"><ProblemNotice problem={run.problem} /></div>
          {run.busy && <div className="mt-3"><LoadingState lines={4} label="Researching the market" /></div>}
        </Section>
      )}

      <ProblemNotice problem={openProblem} />
      {shown && <ReportView run={shown} />}

      <Section title="Earlier reports" hint="Your last reports, newest first.">
        <ProblemNotice problem={historyProblem} onRetry={loadHistory} />
        {history === null && !historyProblem && <LoadingState lines={2} label="Loading earlier reports" />}
        {history !== null && history.length === 0 && <EmptyState compact icon="reports" title="No reports yet" description="Your first report will appear here." />}
        {history !== null && history.length > 0 && (
          <ul className="flex flex-col gap-2">
            {history.map((h) => (
              <li key={h.generationId} className="flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2" style={{ border: "1px solid var(--border-hover)" }}>
                <span className="t-body-sm" style={{ color: "var(--text-3)" }}>
                  {when(h.createdAt)} · <StatusBadge tone={h.status === "COMPLETE" ? "accent" : "negative"}>{h.status === "COMPLETE" ? "Complete" : "Not completed — not charged"}</StatusBadge>
                </span>
                {h.status === "COMPLETE" && <SubmitButton busy={false} busyLabel="" label="Open" onClick={() => open(h.generationId)} />}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ReportView({ run }: { run: TrendRun }) {
  if (run.status === "FAILED" || !run.report) {
    return (
      <Section title="Report">
        <EmptyState icon="reports" title="No report could be built" description={`${run.failureReason ?? "Nothing citable was found."} You were not charged. You can try again later.`} />
      </Section>
    );
  }
  const r = run.report;
  const degraded = r.evidence.degraded_sections;
  return (
    <div className="mt-stack">
      <Section
        title="Your market report"
        hint="Everything below is reported by the sources shown. Attention in a source is not demand, sales or profit."
        action={run.reused ? <StatusBadge tone="neutral">Shown again — no charge</StatusBadge> : <Unit n={run.unitsBilled.cmo} what="report" />}
      >
        {degraded.length > 0 ? (
          <div role="status" className="rounded-xl px-3.5 py-2.5 t-body-sm" style={{ background: "var(--warning-fill)", color: "var(--text-2)" }}>
            <div className="font-bold" style={{ color: "var(--warning)" }}>Some sections are missing or incomplete</div>
            <ul className="mt-1">
              {degraded.map((d) => (
                <li key={d.section}>
                  {SECTION_TITLE[d.section]?.slice(4) ?? d.section}: {d.reason}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="t-body-sm" style={{ color: "var(--text-5)" }}>All requested sections were researched.</div>
        )}
      </Section>
      {SECTION_ORDER.map((id) => (
        <SectionView key={id} id={id} data={r.sections[id]} />
      ))}
      <InterpretationView report={r} />
      <EvidenceView report={r} />
    </div>
  );
}

function SectionView({ id, data }: { id: string; data: TrendSectionData | undefined }) {
  const state = data?.state ?? "UNAVAILABLE";
  return (
    <Section title={SECTION_TITLE[id]} hint={SECTION_HINT[id]} action={<StatusBadge tone={STATE_TONE[state]}>{STATE_LABEL[state]}</StatusBadge>}>
      {data?.reason && <div className="mb-3 t-body-sm" style={{ color: "var(--text-5)" }}>{data.reason}</div>}
      {data && data.findings.length === 0 && state === "UNAVAILABLE" && !data.reason && <EmptyState compact title="Nothing to show" />}
      {id === "REPORTED_TACTICS" && data ? <TacticsView findings={data.findings} /> : (
        <div className="flex flex-col gap-3">{data?.findings.map((f) => <FindingCard key={f.finding_id} f={f} />)}</div>
      )}
    </Section>
  );
}

function TacticsView({ findings }: { findings: TrendFinding[] }) {
  const clear = findings.filter((f) => !f.caution);
  const caution = findings.filter((f) => f.caution);
  return (
    <div className="flex flex-col gap-4">
      {clear.length > 0 && <div className="flex flex-col gap-3">{clear.map((f) => <FindingCard key={f.finding_id} f={f} />)}</div>}
      {caution.length > 0 && (
        <div role="group" aria-label="Tactics with a policy caution" className="rounded-xl p-3" style={{ border: "1px solid var(--warning-border)", background: "var(--warning-fill)" }}>
          <div className="mb-2 t-body-sm font-bold" style={{ color: "var(--warning)" }}>Policy caution — shown for awareness only, with no suggested action</div>
          <div className="flex flex-col gap-3">{caution.map((f) => <FindingCard key={f.finding_id} f={f} />)}</div>
        </div>
      )}
    </div>
  );
}

function FindingCard({ f }: { f: TrendFinding }) {
  const c = f.corroboration ? CORROBORATION[f.corroboration] : null;
  const unassessed = f.policy_risk === "UNASSESSED";
  return (
    <article className="rounded-xl px-3.5 py-3" style={{ border: "1px solid var(--border-hover)", background: "var(--bg-card, transparent)" }}>
      <h3 className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{f.theme}</h3>
      <p className="mt-1 t-body" style={{ color: "var(--text-3)" }}>{f.summary}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {c && <StatusBadge tone={c.tone} title={f.corroboration_label}>{c.label}</StatusBadge>}
        <StatusBadge tone={f.is_stale ? "warning" : "neutral"}>{RECENCY[f.recency_class] ?? f.recency_class}</StatusBadge>
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          {f.independent_source_count} independent source{f.independent_source_count === 1 ? "" : "s"} · freshest {when(f.freshest_published_at)}
        </span>
        {f.news_kind && <StatusBadge tone="info">{f.news_kind.replace("_", " ").toLowerCase()}</StatusBadge>}
        {f.source_class === "OFFICIAL_MARKETPLACE" && <StatusBadge tone="accent">Marketplace page</StatusBadge>}
        {f.buzz_kind && <StatusBadge tone="info">{f.buzz_kind.replace("_", " ").toLowerCase()}</StatusBadge>}
      </div>
      <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{f.corroboration_label}.</div>
      {f.relation_to_niche && <div className="mt-1 t-body-sm" style={{ color: "var(--text-4)" }}>How it relates: {f.relation_to_niche}</div>}
      {f.attention_metrics && f.attention_metrics.length > 0 && (
        <ul className="mt-2 flex flex-col gap-0.5">
          {f.attention_metrics.map((m) => (
            <li key={m.source_url} className="t-meta" style={{ color: "var(--text-5)" }}>
              Views reported by {m.as_reported_by}: {m.value.toLocaleString()} (as of {when(m.as_of)})
            </li>
          ))}
          <li className="t-meta" style={{ color: "var(--text-6)" }}>{f.attention_note ?? "Attention signal — not proof of sales."}</li>
        </ul>
      )}
      {f.claim_status && (
        <div className="mt-2 flex flex-col gap-1">
          <StatusBadge tone="warning">Reported — not verified by Metrion</StatusBadge>
          {unassessed && <div className="t-meta" style={{ color: "var(--text-5)" }}>Policy risk could not be assessed, so no action is suggested.</div>}
          {f.policy_check_line && <div className="t-body-sm font-semibold" style={{ color: "var(--text-3)" }}>{f.policy_check_line}</div>}
        </div>
      )}
      <ul className="mt-2 flex flex-col gap-1">
        {f.sources.map((s) => (
          <li key={s.url} className="t-body-sm">
            <a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a>
            <span style={{ color: "var(--text-6)" }}> · {s.source_type === "VIDEO" ? "video" : "web"} · published {when(s.published_at)} · retrieved {when(s.retrieved_at)}</span>
          </li>
        ))}
      </ul>
      <div className="mt-2 t-meta" style={{ color: "var(--text-6)" }}>{f.limitation_note}</div>
    </article>
  );
}

function InterpretationView({ report }: { report: TrendReport }) {
  const i = report.interpretation;
  return (
    <Section title="6 · What this could mean for your business" hint={i.label}>
      <div className="mb-2"><StatusBadge tone="info">{i.label}</StatusBadge></div>
      {i.items.length === 0 ? (
        <EmptyState compact title="No interpretation this time" description={i.note ?? "Nothing passed the automatic checks."} />
      ) : (
        <ul className="flex flex-col gap-2">
          {i.items.map((it, n) => (
            <li key={n} className="rounded-xl px-3 py-2.5" style={{ border: "1px solid var(--border-hover)" }}>
              <div className="t-body" style={{ color: "var(--text-2)" }}>{it.statement}</div>
              <div className="mt-1 flex flex-wrap items-center gap-2 t-meta" style={{ color: "var(--text-6)" }}>
                <StatusBadge tone="neutral">{it.action_type.replace(/_/g, " ").toLowerCase()}</StatusBadge>
                <span>Based on: {it.derived_from_finding_ids.join(", ")}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function EvidenceView({ report }: { report: TrendReport }) {
  const e = report.evidence;
  return (
    <Section title="7 · Evidence and limitations" hint="Where everything above came from, what was missing, and what this report cannot tell you.">
      <div className="flex flex-col gap-4">
        <div>
          <div className="mb-1 t-body-sm font-bold" style={{ color: "var(--text-3)" }}>Limits of this report</div>
          <ul className="list-disc pl-5">
            {e.data_gaps.map((g) => (
              <li key={g} className="t-body-sm" style={{ color: "var(--text-4)" }}>{g}</li>
            ))}
          </ul>
        </div>
        <div className="t-body-sm" style={{ color: "var(--text-4)" }}>
          Searches used: {e.providers_and_modes_used.join(", ") || "none"}. {String(e.provider_accounting.note ?? "")}
          {e.unresearched_confirmed_terms.length > 0 && <> Not researched this time: {e.unresearched_confirmed_terms.join(", ")}.</>}
          {e.withheld_for_instruction_like_text > 0 && <> {e.withheld_for_instruction_like_text} result(s) were left out because their text tried to give instructions.</>}
          {e.dropped_by_source_cap > 0 && <> {e.dropped_by_source_cap} result(s) were not read because of the source limit.</>}
        </div>
        <div className="mt-table-wrap">
          <table className="mt-table">
            <caption className="sr-only">Every source cited in this report</caption>
            <thead><tr><th scope="col">Source</th><th scope="col">Type</th><th scope="col">Published</th><th scope="col">Retrieved</th><th scope="col">Used by</th></tr></thead>
            <tbody>
              {e.sources.map((s) => (
                <tr key={s.url}>
                  <td className="break-words"><a className="underline" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a>{s.collapsed_into && <span className="t-meta" style={{ color: "var(--text-6)" }}> (same story as another source)</span>}</td>
                  <td>{s.source_type === "VIDEO" ? "Video" : "Web"} · {s.source_class === "OFFICIAL_MARKETPLACE" ? "marketplace" : "third party"}</td>
                  <td>{when(s.published_at)}</td>
                  <td>{when(s.retrieved_at)}</td>
                  <td>{s.cited_by.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="t-meta" style={{ color: "var(--text-6)" }}>Report id and exact searches are saved for your records.</div>
      </div>
    </Section>
  );
}

