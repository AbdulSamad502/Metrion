"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Tabs } from "@/components/ui/Tabs";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { AsyncBlock, CopyButton, fmtDate, Hint, LengthMeter, Pill, SectionCard, ShowcaseRefreshProvider, useAsync, withLimit } from "@/components/cmo/showcaseUi";
import { RefreshButton } from "@/components/overview/parts";
import { Spinner } from "@/components/ui/LoadingState";
import {
  MARKETPLACES, type CopyPack, type Marketplace, type ShowcaseClient, type ShowcaseTitle, type TitleUsage, type TrendFinding, type TrendReport,
} from "@/lib/cmoShowcase";

/** The read-only CMO showcase (ceo-cmo-delegation.md §6.8). It shows what the CEO's CMO already produced and saved. There is no form,
 * no generate / regenerate / select-to-run / approve control and no call to a CMO POST route: the only write is the fire-and-forget
 * usage event a copy or "mark as used" emits (CD14). Every number shown (chars, bytes, limits, counts) is stored by the backend. */

const safeHref = (u: string | null) => (u && /^https?:\/\//i.test(u) ? u : null);
const sectionTabs = MARKETPLACES.map((m) => ({ id: m.id, label: m.label }));

export function ShowcaseDashboard({ client, sample = false }: { client: ShowcaseClient; sample?: boolean }) {
  const [sku, setSku] = useState("");
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [marketplace, setMarketplace] = useState<Marketplace>("AMAZON");
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(t);
  }, [qInput]);
  const products = useAsync(() => client.products(), [client]);
  const filters = { sku: sku || undefined, q: q || undefined };
  // "Refresh" re-reads every section for the SAME filters; the sections report when they are busy so the button can say so and cannot be pressed twice.
  const [refreshKey, setRefreshKey] = useState(0);
  const [busy, setBusy] = useState(0);
  const busyIds = useRef(new Set<string>());
  const report = useCallback((id: string, isBusy: boolean) => {
    if (isBusy) busyIds.current.add(id);
    else busyIds.current.delete(id);
    setBusy(busyIds.current.size);
  }, []);
  const productLabel = sku ? (products.state.status === "ready" ? products.state.data.items.find((p) => p.sku === sku)?.label : undefined) ?? sku : null;

  return (
    <ShowcaseRefreshProvider value={{ key: refreshKey, report }}>
    <div className="ov mt-content">
      {sample && (
        <div role="status" className="ov-note">
          SAMPLE DATA - local visual check only. Nothing below is real or saved by a seller.
        </div>
      )}

      <header className="ov-head ov-rise">
        <div className="min-w-0">
          <h2 className="ov-h">Your listing copy</h2>
          <p className="ov-body" style={{ marginTop: 4 }}>Read-only. Ask the CEO to create or change anything.</p>
        </div>
        <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--brand min-h-10">
          Ask the CEO
        </Link>
      </header>

      <div className="cmo-toolbar ov-rise" style={{ ["--i" as string]: 1 }} data-testid="cmo-context">
        <div className="cmo-filters">
          <label>
            Product
            <select value={sku} onChange={(e) => setSku(e.target.value)} className="cmo-input" aria-label="Filter by product">
              <option value="">All products</option>
              {products.state.status === "ready" && products.state.data.items.map((p) => <option key={p.sku} value={p.sku}>{p.label}</option>)}
            </select>
          </label>
          <input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="Search saved titles, packs, hashtags" aria-label="Search saved results" className="cmo-input" style={{ width: 320, maxWidth: "100%" }} />
        </div>
        <div className="ov-head-r">
          <p role="status" className="ov-meta" style={{ margin: 0 }}>
            {busy > 0 ? "Refreshing… what is shown is the last result that loaded." : `Showing ${productLabel ?? "all products"}${q ? ` matching “${q}”` : ""}.`}
          </p>
          <RefreshButton spinning={busy > 0} onClick={() => setRefreshKey((n) => n + 1)} />
        </div>
      </div>

      <Tabs tabs={sectionTabs} active={marketplace} onChange={(id) => setMarketplace(id as Marketplace)} label="Marketplace" idPrefix="cmo-mp" />
      <TitlesAndPacks client={client} marketplace={marketplace} {...filters} />
      <NewsSection client={client} />
      <HashtagsAndCompliance client={client} marketplace={marketplace} {...filters} />
    </div>
    </ShowcaseRefreshProvider>
  );
}

// ---------------------------------------------------------------------------------------------------------- news
type NewsItem = { key: string; finding: TrendFinding; section: string; report: TrendReport };

function NewsSection({ client }: { client: ShowcaseClient }) {
  const trends = useAsync(() => client.trends(), [client]);
  return (
    <SectionCard title="Market Trends & Fresh E-Commerce News" >
      <AsyncBlock
        a={trends} label="market news"
        isEmpty={(d) => d.items.length === 0}
        empty="No news yet. Ask the CEO."
      >
        {(d) => {
          const latest = d.items[0];
          const items: NewsItem[] = d.items.flatMap((report) => report.sections.flatMap((s, si) => s.findings.map((finding, fi) => ({ key: `${report.generationId}-${si}-${fi}`, finding, section: s.name, report }))));
          return (
            <>
              <p className="ov-meta">
                {latest.nicheTerms.length > 0 && <>Niche: <strong style={{ color: "var(--ov-ink)" }}>{latest.nicheTerms.join(", ")}</strong> - </>}
                Updated {fmtDate(latest.createdAt)}{latest.interpretationLabel ? ` - ${latest.interpretationLabel}` : ""}
              </p>
              {items.length === 0 ? (
                <Hint>The latest report has no findings.</Hint>
              ) : (
                <ul className="cmo-news">
                  {items.slice(0, 9).map(({ key, finding, section, report }) => {
                    const href = safeHref(finding.sourceUrl);
                    return (
                      <li key={key} className="cmo-item">
                        <div className="cmo-item-body">
                          <div className="cmo-meta-row">
                            <Pill tone="neutral">{section}</Pill>
                            <span className="ov-meta">
                              {href ? <a href={href} target="_blank" rel="noreferrer noopener" style={{ color: "var(--ov-brand-ink)", textDecoration: "underline" }}>{finding.sourceName}</a> : finding.sourceName}
                            </span>
                          </div>
                          <p className="ov-title">{finding.text}</p>
                          <p className="ov-meta">
                            {finding.publishedAt ? `Published ${fmtDate(finding.publishedAt)}` : "Publication date not stated"} - retrieved {fmtDate(finding.retrievedAt)}
                            {finding.corroboration ? ` - ${finding.corroboration}` : ""}
                          </p>
                          {report.evidenceRef && <p className="ov-meta">Evidence and limitations: {report.evidenceRef}</p>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          );
        }}
      </AsyncBlock>
    </SectionCard>
  );
}

// ------------------------------------------------------------------------------------------- titles + copy packs
function usageLine(u: TitleUsage | null): string | null {
  if (!u) return null;
  const parts: string[] = [];
  if (u.copied) parts.push(`copied ${u.copied} time${u.copied === 1 ? "" : "s"}`);
  if (u.markedUsed) parts.push(`marked used ${u.markedUsed} time${u.markedUsed === 1 ? "" : "s"}`);
  if (parts.length === 0) return null;
  return parts.join(", ") + (u.since ? `, recorded since ${fmtDate(u.since)}` : "");
}

function TitlesAndPacks({ client, marketplace, sku, q }: { client: ShowcaseClient; marketplace: Marketplace; sku?: string; q?: string }) {
  const [view, setView] = useState<"recent" | "frequent">("recent");
  const [approvedOnly, setApprovedOnly] = useState(false);
  const [detail, setDetail] = useState<{ kind: "title"; item: ShowcaseTitle } | { kind: "pack"; item: CopyPack } | null>(null);
  const titles = useAsync(() => client.titles({ marketplace, sku, q, view, approvedOnly }), [client, marketplace, sku, q, view, approvedOnly]);
  const packs = useAsync(() => client.copyPacks({ marketplace, sku, q }), [client, marketplace, sku, q]);
  const [packId, setPackId] = useState<string | null>(null);
  const packItems = packs.state.status === "ready" ? packs.state.data.items : [];
  const packIx = Math.max(0, packItems.findIndex((x) => x.generationId === packId)); // a stale/unknown selection falls back to the newest pack

  const track = (generationId: string, kind: "VIEWED" | "COPIED" | "MARKED_USED", optionId?: string, resultPart?: string) =>
    client.recordUsage({ generationId, optionId, resultPart, kind, surface: "DASHBOARD" });
  const open = (d: NonNullable<typeof detail>) => {
    setDetail(d);
    track(d.item.generationId, "VIEWED", d.kind === "title" ? d.item.optionId : undefined);
  };

  const marketLabel = MARKETPLACES.find((m) => m.id === marketplace)?.label ?? marketplace;
  const titleItems = titles.state.status === "ready" ? titles.state.data.items : null;
  return (
    <>
      {titleItems && packs.state.status === "ready" && (
        <section className="ov-card ov-hero cmo-hero ov-rise" aria-label={`${marketLabel} listing summary`}>
          <div className="cmo-hero-head">
            <p className="ov-h">{marketLabel} listings</p>
            <p className="ov-meta">Saved results</p>
          </div>
          <dl className="cmo-hero-stats">
            <div><dd className="ov-fig">{titleItems.length}</dd><dt className="ov-meta">Titles shown</dt></div>
            <div><dd className="ov-fig">{titleItems.filter((t) => t.approved).length}</dd><dt className="ov-meta">Titles approved</dt></div>
            <div><dd className="ov-fig">{packItems.length}</dd><dt className="ov-meta">Copy packs</dt></div>
          </dl>
        </section>
      )}
      <div className="cmo-work">
      <SectionCard
        title="Frequently Used SEO Titles"
        
        action={
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
            <div className="cmo-seg" role="group" aria-label="Title view">
              {(["recent", "frequent"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className="mt-focus">
                  {v === "recent" ? "Recent" : "Frequently used"}
                </button>
              ))}
            </div>
            <label className="cmo-check">
              <input type="checkbox" checked={approvedOnly} onChange={(e) => setApprovedOnly(e.target.checked)} /> Approved only
            </label>
          </div>
        }
      >
        <AsyncBlock
          a={titles} label="titles"
          isEmpty={(d) => d.items.length === 0 || (view === "frequent" && !d.usage.available)}
          empty={view === "frequent" ? "Not available yet: no copies recorded. Switch to Recent." : `No saved ${marketLabel} titles. Ask the CEO.`}
        >
          {(d) => (
            <ul className="cmo-rules">
              {d.items.map((t) => {
                const u = usageLine(t.usage);
                return (
                  <li key={t.optionId} className={`cmo-item${t.approved ? " cmo-item--approved" : ""}`}>
                    <div className="cmo-item-body">
                      <p className="ov-title">{t.titleText}</p>
                      <div className="cmo-meta-row">
                        {t.approved && <Pill tone="accent" title={`Approved ${fmtDate(t.approved.approvedAt)}`}>Approved</Pill>}
                        <span className="ov-meta">{withLimit(t.charCount, t.maxChars, "chars")}</span>
                        <LengthMeter n={t.charCount} max={t.maxChars} />
                        <span className="ov-meta">{t.productLabel} - {fmtDate(t.generatedAt)}</span>
                      </div>
                      {u && <p className="ov-meta">{u}</p>}
                      <div className="cmo-actions">
                        <CopyButton text={t.titleText} onCopied={() => track(t.generationId, "COPIED", t.optionId, "TITLE")} />
                        <button type="button" onClick={() => open({ kind: "title", item: t })} className="ov-btn ov-btn--ghost min-h-10">Details</button>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </AsyncBlock>
      </SectionCard>

      <SectionCard title="Grounded Marketplace Copy Pack" 
        action={packItems[packIx] ? <CopyButton label="Copy Full Pack" text={packText(packItems[packIx])} onCopied={() => track(packItems[packIx].generationId, "COPIED", undefined, "FULL_PACK")} /> : undefined}>
        <AsyncBlock a={packs} label="copy packs" isEmpty={(d) => d.items.length === 0} empty={`No ${marketLabel} copy pack yet. Ask the CEO.`}>
          {(d) => {
            const p = d.items[packIx];
            const gen = p.generationId;
            return (
              <div className="cmo-pack">
                {d.items.length > 1 && (
                  <div className="ov-chips" role="group" aria-label="Saved packs">
                    {d.items.map((x, i) => (
                      <button key={x.generationId} type="button" aria-pressed={i === packIx} onClick={() => setPackId(x.generationId)} className="ci-pick mt-focus">
                        {x.productLabel} - {fmtDate(x.generatedAt)}
                      </button>
                    ))}
                  </div>
                )}
                <p className="ov-meta">
                  Grounded on: <span style={{ color: "var(--ov-ink)", fontWeight: 700 }}>{p.groundedOn.titleText}</span> ({p.groundedOn.basis}) - {p.productLabel} - {fmtDate(p.generatedAt)}
                </p>
                <PackRow heading="Feature bullets" />
                {p.bullets.map((b, i) => (
                  <div key={i} className="cmo-block">
                    <div className="cmo-row">
                      <div className="cmo-row-main"><p className="ov-body" style={{ color: "var(--ov-ink)" }}>{b.text}</p><p className="ov-meta">{withLimit(b.chars, b.max, "chars")}</p><LengthMeter n={b.chars} max={b.max} /></div>
                      <CopyButton text={b.text} onCopied={() => track(gen, "COPIED", undefined, `BULLET_${i + 1}`)} />
                    </div>
                  </div>
                ))}
                <PackRow heading="Product description" />
                <div className="cmo-block cmo-block--wide">
                  <div className="cmo-row">
                    <div className="cmo-row-main"><p className="ov-body" style={{ color: "var(--ov-ink)", whiteSpace: "pre-wrap" }}>{p.description.text}</p><p className="ov-meta">{withLimit(p.description.chars, p.description.max, "chars")}</p><LengthMeter n={p.description.chars} max={p.description.max} /></div>
                    <CopyButton text={p.description.text} onCopied={() => track(gen, "COPIED", undefined, "DESCRIPTION")} />
                  </div>
                </div>
                {p.backendTerms && (
                  <>
                    <PackRow heading="Backend search terms" />
                    <div className="cmo-block cmo-block--wide">
                      <div className="cmo-row">
                        <div className="cmo-row-main"><p className="ov-body" style={{ color: "var(--ov-ink)" }}>{p.backendTerms.text}</p><p className="ov-meta">{withLimit(p.backendTerms.bytes, p.backendTerms.maxBytes, "bytes")}</p><LengthMeter n={p.backendTerms.bytes} max={p.backendTerms.maxBytes} /></div>
                        <CopyButton text={p.backendTerms.text} onCopied={() => track(gen, "COPIED", undefined, "BACKEND_TERMS")} />
                      </div>
                    </div>
                  </>
                )}
                {p.labels.length > 0 && <p className="ov-meta">{p.labels.join(" - ")}</p>}
                <div><button type="button" onClick={() => open({ kind: "pack", item: p })} className="ov-btn min-h-10">Pack details</button></div>
              </div>
            );
          }}
        </AsyncBlock>
      </SectionCard>

      </div>

      <DetailDrawer open={detail !== null} onClose={() => setDetail(null)} title={detail?.kind === "title" ? "Saved title" : "Saved copy pack"} subtitle={detail ? `${detail.item.productLabel} - ${detail.item.marketplace}` : undefined}>
        {detail && <DetailBody detail={detail} onMarkUsed={(g, o) => client.recordUsage({ generationId: g, optionId: o, resultPart: detail.kind === "title" ? "TITLE" : "FULL_PACK", kind: "MARKED_USED", surface: "DASHBOARD" })} />}
      </DetailDrawer>
    </>
  );
}

function PackRow({ heading }: { heading: string }) {
  return <h3 className="cmo-label">{heading}</h3>;
}

function packText(p: CopyPack): string {
  return [
    ...p.bullets.map((b) => `- ${b.text}`),
    "",
    p.description.text,
    ...(p.backendTerms ? ["", `Backend search terms: ${p.backendTerms.text}`] : []),
  ].join("\n");
}

function DetailBody({ detail, onMarkUsed }: { detail: { kind: "title"; item: ShowcaseTitle } | { kind: "pack"; item: CopyPack }; onMarkUsed: (generationId: string, optionId?: string) => void | Promise<boolean> }) {
  // "Marked as used" is shown only once the server has accepted the event; a refusal says so and can be retried.
  const [mark, setMark] = useState<"idle" | "saving" | "done" | "failed">("idle");
  const markUsed = async () => {
    if (mark === "saving" || mark === "done") return;
    setMark("saving");
    const ok = await onMarkUsed(detail.item.generationId, detail.kind === "title" ? detail.item.optionId : undefined);
    setMark(ok === false ? "failed" : "done");
  };
  const rows: [string, string][] = [];
  const it = detail.item;
  rows.push(["Product", `${it.productLabel} (${it.sku})`], ["Marketplace", it.marketplace], ["Generated", fmtDate(it.generatedAt)], ["Created via", it.origin.kind === "CEO_CHAT" ? "CEO chat" : "Earlier workflow"], ["Generation id", it.generationId]);
  if (it.origin.investigationId) rows.push(["Investigation", it.origin.investigationId]);
  if (it.origin.turnId) rows.push(["Turn", it.origin.turnId]);
  if (detail.kind === "title") {
    const t = detail.item;
    rows.push(["Length", withLimit(t.charCount, t.maxChars, "chars")]);
    if (t.constraint) rows.push(["Limit source", `${t.constraint.sourceUrl ?? "not stated"} (verified ${fmtDate(t.constraint.verifiedAt)})`]);
    rows.push(["Approval", t.approved ? `Approved ${fmtDate(t.approved.approvedAt)}${t.approved.editedBySeller ? " (edited by seller)" : ""}` : "Not approved"]);
  } else {
    rows.push(["Grounded on", detail.item.groundedOn.titleText]);
  }
  return (
    <div className="cmo-list">
      {detail.kind === "title" && <p className="ov-title">{detail.item.titleText}</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 ov-body">
        {rows.map(([k, v]) => (<div key={k} className="contents"><dt className="ov-meta">{k}</dt><dd className="break-words" style={{ color: "var(--ov-ink)", margin: 0 }}>{v}</dd></div>))}
      </dl>
      <div className="cmo-actions">
        <button type="button" disabled={mark === "saving" || mark === "done"} aria-busy={mark === "saving"} onClick={() => void markUsed()} className="ov-btn min-h-10">
          {mark === "saving" && <Spinner size={12} />}
          {mark === "saving" ? "Recording…" : mark === "done" ? "Marked as used" : mark === "failed" ? "Try again" : "Mark as used"}
        </button>
        {mark === "failed" && <span role="alert" className="ov-meta" style={{ color: "var(--ov-warn)" }}>Could not record that. Nothing was published and nothing else changed.</span>}
      </div>
      <p className="ov-meta">Only records that you used it. Nothing is published.</p>
    </div>
  );
}

// ----------------------------------------------------------------------------------- hashtags + compliance summary
function HashtagsAndCompliance({ client, marketplace, sku, q }: { client: ShowcaseClient; marketplace: Marketplace; sku?: string; q?: string }) {
  const tags = useAsync(() => client.hashtags({ sku, q }), [client, sku, q]);
  const comp = useAsync(() => client.compliance({ sku, marketplace }), [client, sku, marketplace]);
  return (
    <SectionCard title="Social Marketing Hashtags & Compliance Summary" hint="Not a listing field">
      <AsyncBlock a={tags} label="hashtags" isEmpty={(d) => d.items.length === 0} empty="No hashtag sets yet. Ask the CEO.">
        {(d) => (
          <ul className="cmo-rules">
            {d.items.map((h) => (
              <li key={h.generationId + h.sku + h.generatedAt} className="cmo-item">
                <div className="cmo-item-body">
                  <div className="cmo-row">
                    <div className="cmo-row-main">
                      <p className="ov-meta">{h.productLabel} - {fmtDate(h.generatedAt)}</p>
                      <p className="ov-title" style={{ overflowWrap: "anywhere", color: "var(--ov-brand-ink)" }}>{h.hashtags.join(" ")}</p>
                    </div>
                    <CopyButton text={h.hashtags.join(" ")} onCopied={() => client.recordUsage({ generationId: h.generationId, resultPart: "HASHTAGS", kind: "COPIED", surface: "DASHBOARD" })} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </AsyncBlock>
      <h3 className="cmo-label" style={{ marginTop: 16 }}>Compliance summary (stored checks only)</h3>
      <AsyncBlock a={comp} label="compliance summary" isEmpty={(d) => !d.counts || d.counts.length === 0} empty="No checks stored yet.">
        {(d) => (
          <ul className="cmo-list" style={{ gap: 8 }}>
            {d.counts!.map((c) => (
              <li key={c.label} className="ov-body">
                <strong style={{ color: "var(--ov-ink)" }}>{c.count}</strong> {c.label} <span className="ov-meta">({c.basis})</span>
              </li>
            ))}
          </ul>
        )}
      </AsyncBlock>
      <p className="ov-meta" style={{ marginTop: 16 }}>Nothing is sent to a marketplace.</p>
    </SectionCard>
  );
}
