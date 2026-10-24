"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Tabs } from "@/components/ui/Tabs";
import { DetailDrawer } from "@/components/ui/DetailDrawer";
import { AsyncBlock, Card, CopyButton, fmtDate, Hint, Pill, SectionCard, ShowcaseRefreshProvider, useAsync, withLimit } from "@/components/cmo/showcaseUi";
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
    <div className="mt-content flex flex-col gap-5">
      {sample && (
        <div role="status" className="rounded-xl px-4 py-2.5 t-body-sm font-bold" style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", color: "var(--warning)" }}>
          SAMPLE DATA - local visual check only. Nothing below is real or saved by a seller.
        </div>
      )}

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="t-headline font-bold" style={{ color: "var(--text-1)" }}>Slim CMO Dashboard</h2>
          <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Saved SEO titles and marketplace copy (Amazon, Flipkart, Meesho) - read-only library</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 t-meta" style={{ color: "var(--text-5)" }}>
            Product
            <select value={sku} onChange={(e) => setSku(e.target.value)} className="mt-input rounded-lg px-3 py-1.5 t-body-sm" aria-label="Filter by product">
              <option value="">All products</option>
              {products.state.status === "ready" && products.state.data.items.map((p) => <option key={p.sku} value={p.sku}>{p.label}</option>)}
            </select>
          </label>
          <input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="Search saved titles, packs, hashtags" aria-label="Search saved results" className="mt-input w-64 max-w-full rounded-lg px-3 py-1.5 t-body-sm" />
        </div>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3" style={{ background: "var(--accent-fill-subtle)", border: "1px solid var(--accent-border-default)" }}>
        <p className="t-body-sm" style={{ color: "var(--text-3)" }}>
          <strong style={{ color: "var(--text-1)" }}>To create or change anything, ask the CEO.</strong> This page only shows what is already saved.
        </p>
        <Link href="/dashboard/ceo-hub" className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-meta font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
          Ask the CEO
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="cmo-context">
        <p role="status" className="m-0 t-meta" style={{ color: "var(--text-5)" }}>
          {busy > 0 ? "Refreshing… what is shown is the last result that loaded." : `Showing saved results for ${productLabel ?? "all products"}${q ? ` matching “${q}”` : ""}.`}
        </p>
        <button type="button" onClick={() => setRefreshKey((n) => n + 1)} disabled={busy > 0} className="mt-btn mt-btn-secondary mt-focus inline-flex min-h-[40px] items-center gap-2 rounded-lg px-3 py-1 t-meta font-bold disabled:cursor-not-allowed" style={{ opacity: busy > 0 ? 0.7 : 1 }}>
          {busy > 0 && <Spinner size={12} />}
          {busy > 0 ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <NewsSection client={client} />
      <TitlesAndPacks client={client} marketplace={marketplace} setMarketplace={setMarketplace} {...filters} />
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
    <SectionCard title="Market Trends & Fresh E-Commerce News" hint="From saved market-trend reports only">
      <AsyncBlock
        a={trends} label="market news"
        isEmpty={(d) => d.items.length === 0}
        empty="No news fetched yet - ask the CEO for market news"
      >
        {(d) => {
          const latest = d.items[0];
          const items: NewsItem[] = d.items.flatMap((report) => report.sections.flatMap((s, si) => s.findings.map((finding, fi) => ({ key: `${report.generationId}-${si}-${fi}`, finding, section: s.name, report }))));
          return (
            <>
              <p className="mb-3 t-meta" style={{ color: "var(--text-6)" }}>
                {latest.nicheTerms.length > 0 && <>Niche: <strong style={{ color: "var(--text-1)" }}>{latest.nicheTerms.join(", ")}</strong> - </>}
                Updated {fmtDate(latest.createdAt)}{latest.interpretationLabel ? ` - ${latest.interpretationLabel}` : ""}
              </p>
              {items.length === 0 ? (
                <Hint>The latest report has no findings.</Hint>
              ) : (
                <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {items.slice(0, 9).map(({ key, finding, section, report }) => {
                    const href = safeHref(finding.sourceUrl);
                    return (
                      <li key={key}>
                        <Card className="h-full">
                          <div className="mb-2 flex flex-wrap items-center gap-1.5">
                            <Pill tone="neutral">{section}</Pill>
                            <span className="t-meta" style={{ color: "var(--text-5)" }}>
                              {href ? <a href={href} target="_blank" rel="noreferrer noopener" className="underline">{finding.sourceName}</a> : finding.sourceName}
                            </span>
                          </div>
                          <p className="t-body font-bold" style={{ color: "var(--text-1)" }}>{finding.text}</p>
                          <p className="mt-2 t-meta" style={{ color: "var(--text-6)" }}>
                            {finding.publishedAt ? `Published ${fmtDate(finding.publishedAt)}` : "Publication date not stated"} - retrieved {fmtDate(finding.retrievedAt)}
                            {finding.corroboration ? ` - ${finding.corroboration}` : ""}
                          </p>
                          {report.evidenceRef && <p className="mt-1 t-micro" style={{ color: "var(--text-7)" }}>Evidence and limitations: {report.evidenceRef}</p>}
                        </Card>
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

function TitlesAndPacks({ client, marketplace, setMarketplace, sku, q }: { client: ShowcaseClient; marketplace: Marketplace; setMarketplace: (m: Marketplace) => void; sku?: string; q?: string }) {
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
  return (
    <>
      <SectionCard
        title="Frequently Used SEO Titles"
        hint="Saved titles with their stored character counts and marketplace limits"
        action={
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex overflow-hidden rounded-lg" role="group" aria-label="Title view" style={{ border: "1px solid var(--border-default)" }}>
              {(["recent", "frequent"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className="mt-focus min-h-[40px] px-3 py-1 t-meta font-bold" style={view === v ? { background: "var(--accent-fill-default)", color: "var(--accent)" } : { color: "var(--text-5)" }}>
                  {v === "recent" ? "Recent" : "Frequently used"}
                </button>
              ))}
            </div>
            <label className="flex min-h-[40px] items-center gap-1.5 t-meta" style={{ color: "var(--text-5)" }}>
              <input type="checkbox" checked={approvedOnly} onChange={(e) => setApprovedOnly(e.target.checked)} /> Approved only
            </label>
          </div>
        }
      >
        <div className="mb-4">
          <Tabs tabs={sectionTabs} active={marketplace} onChange={(id) => setMarketplace(id as Marketplace)} label="Marketplace" idPrefix="cmo-mp" />
        </div>
        <AsyncBlock
          a={titles} label="titles"
          isEmpty={(d) => d.items.length === 0 || (view === "frequent" && !d.usage.available)}
          empty={view === "frequent" ? "Frequently used unavailable - usage is not recorded yet. Switch to Recent to see saved titles." : `No saved ${marketLabel} titles match. Ask the CEO to create titles.`}
        >
          {(d) => (
            <ul className="flex flex-col gap-2.5">
              {d.items.map((t) => {
                const u = usageLine(t.usage);
                return (
                  <li key={t.optionId}>
                    <Card accent={!!t.approved}>
                      <div className="flex flex-wrap items-center gap-2">
                        {t.approved && <Pill tone="accent" title={`Approved ${fmtDate(t.approved.approvedAt)}`}>Approved</Pill>}
                        <span className="t-meta" style={{ color: "var(--text-6)" }}>{withLimit(t.charCount, t.maxChars, "chars")}</span>
                        <span className="t-meta" style={{ color: "var(--text-7)" }}>{t.productLabel} - {fmtDate(t.generatedAt)}</span>
                      </div>
                      <p className="mt-1.5 t-body font-bold" style={{ color: "var(--text-1)" }}>{t.titleText}</p>
                      {u && <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{u}</p>}
                      <div className="mt-2 flex gap-2">
                        <CopyButton text={t.titleText} onCopied={() => track(t.generationId, "COPIED", t.optionId, "TITLE")} />
                        <button type="button" onClick={() => open({ kind: "title", item: t })} className="mt-btn mt-focus min-h-[40px] rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}>Details</button>
                      </div>
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}
        </AsyncBlock>
      </SectionCard>

      <SectionCard title="Grounded Marketplace Copy Pack" hint={`${marketLabel}: bullets, description and search terms built from a saved title`}
        action={packItems[packIx] ? <CopyButton label="Copy Full Pack" text={packText(packItems[packIx])} onCopied={() => track(packItems[packIx].generationId, "COPIED", undefined, "FULL_PACK")} /> : undefined}>
        <AsyncBlock a={packs} label="copy packs" isEmpty={(d) => d.items.length === 0} empty={`No saved ${marketLabel} copy pack yet. Ask the CEO to create one.`}>
          {(d) => {
            const p = d.items[packIx];
            const gen = p.generationId;
            return (
              <div className="flex flex-col gap-3">
                {d.items.length > 1 && (
                  <div className="flex flex-wrap gap-1.5" role="group" aria-label="Saved packs">
                    {d.items.map((x, i) => (
                      <button key={x.generationId} type="button" aria-pressed={i === packIx} onClick={() => setPackId(x.generationId)} className="mt-focus min-h-[40px] rounded-lg px-2.5 py-1 t-meta" style={i === packIx ? { background: "var(--accent-fill-default)", color: "var(--accent)" } : { border: "1px solid var(--border-default)", color: "var(--text-5)" }}>
                        {x.productLabel} - {fmtDate(x.generatedAt)}
                      </button>
                    ))}
                  </div>
                )}
                <p className="t-meta" style={{ color: "var(--text-6)" }}>
                  Grounded on: <span style={{ color: "var(--text-3)" }}>{p.groundedOn.titleText}</span> ({p.groundedOn.basis}) - {p.productLabel} - {fmtDate(p.generatedAt)}
                </p>
                <PackRow heading="Feature bullets" />
                {p.bullets.map((b, i) => (
                  <Card key={i}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0"><p className="t-body" style={{ color: "var(--text-2)" }}>{b.text}</p><p className="mt-1 t-micro" style={{ color: "var(--text-7)" }}>{withLimit(b.chars, b.max, "chars")}</p></div>
                      <CopyButton text={b.text} onCopied={() => track(gen, "COPIED", undefined, `BULLET_${i + 1}`)} />
                    </div>
                  </Card>
                ))}
                <PackRow heading="Product description" />
                <Card>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0"><p className="whitespace-pre-wrap t-body" style={{ color: "var(--text-2)" }}>{p.description.text}</p><p className="mt-1 t-micro" style={{ color: "var(--text-7)" }}>{withLimit(p.description.chars, p.description.max, "chars")}</p></div>
                    <CopyButton text={p.description.text} onCopied={() => track(gen, "COPIED", undefined, "DESCRIPTION")} />
                  </div>
                </Card>
                {p.backendTerms && (
                  <>
                    <PackRow heading="Backend search terms" />
                    <Card>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0"><p className="t-body" style={{ color: "var(--text-2)" }}>{p.backendTerms.text}</p><p className="mt-1 t-micro" style={{ color: "var(--text-7)" }}>{withLimit(p.backendTerms.bytes, p.backendTerms.maxBytes, "bytes")}</p></div>
                        <CopyButton text={p.backendTerms.text} onCopied={() => track(gen, "COPIED", undefined, "BACKEND_TERMS")} />
                      </div>
                    </Card>
                  </>
                )}
                {p.labels.length > 0 && <p className="t-micro" style={{ color: "var(--text-7)" }}>{p.labels.join(" - ")}</p>}
                <div><button type="button" onClick={() => open({ kind: "pack", item: p })} className="mt-btn mt-focus min-h-[40px] rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}>Pack details</button></div>
              </div>
            );
          }}
        </AsyncBlock>
      </SectionCard>

      <DetailDrawer open={detail !== null} onClose={() => setDetail(null)} title={detail?.kind === "title" ? "Saved title" : "Saved copy pack"} subtitle={detail ? `${detail.item.productLabel} - ${detail.item.marketplace}` : undefined}>
        {detail && <DetailBody detail={detail} onMarkUsed={(g, o) => client.recordUsage({ generationId: g, optionId: o, resultPart: detail.kind === "title" ? "TITLE" : "FULL_PACK", kind: "MARKED_USED", surface: "DASHBOARD" })} />}
      </DetailDrawer>
    </>
  );
}

function PackRow({ heading }: { heading: string }) {
  return <h3 className="t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>{heading}</h3>;
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
    <div className="flex flex-col gap-4">
      {detail.kind === "title" && <p className="t-body font-bold" style={{ color: "var(--text-1)" }}>{detail.item.titleText}</p>}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 t-body-sm">
        {rows.map(([k, v]) => (<div key={k} className="contents"><dt style={{ color: "var(--text-6)" }}>{k}</dt><dd className="break-words" style={{ color: "var(--text-2)" }}>{v}</dd></div>))}
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={mark === "saving" || mark === "done"} aria-busy={mark === "saving"} onClick={() => void markUsed()} className="mt-btn mt-focus inline-flex min-h-[40px] items-center gap-2 rounded-lg px-3 py-1 t-meta font-bold disabled:opacity-60" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
          {mark === "saving" && <Spinner size={12} />}
          {mark === "saving" ? "Recording…" : mark === "done" ? "Marked as used" : mark === "failed" ? "Try again" : "Mark as used"}
        </button>
        {mark === "failed" && <span role="alert" className="t-meta" style={{ color: "var(--warning)" }}>Could not record that. Nothing was published and nothing else changed.</span>}
      </div>
      <p className="t-meta" style={{ color: "var(--text-7)" }}>Marking as used only records that you used this yourself. Nothing is published for you.</p>
    </div>
  );
}

// ----------------------------------------------------------------------------------- hashtags + compliance summary
function HashtagsAndCompliance({ client, marketplace, sku, q }: { client: ShowcaseClient; marketplace: Marketplace; sku?: string; q?: string }) {
  const tags = useAsync(() => client.hashtags({ sku, q }), [client, sku, q]);
  const comp = useAsync(() => client.compliance({ sku, marketplace }), [client, sku, marketplace]);
  return (
    <SectionCard title="Social Marketing Hashtags & Compliance Summary" hint="Separate marketing suggestions - not a marketplace listing field">
      <AsyncBlock a={tags} label="hashtags" isEmpty={(d) => d.items.length === 0} empty="No saved hashtag sets yet. Ask the CEO for social hashtags.">
        {(d) => (
          <ul className="flex flex-col gap-2.5">
            {d.items.map((h) => (
              <li key={h.generationId + h.sku + h.generatedAt}>
                <Card>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="t-meta" style={{ color: "var(--text-7)" }}>{h.productLabel} - {fmtDate(h.generatedAt)}</p>
                      <p className="mt-1 break-words t-body font-bold" style={{ color: "var(--text-1)" }}>{h.hashtags.join(" ")}</p>
                    </div>
                    <CopyButton text={h.hashtags.join(" ")} onCopied={() => client.recordUsage({ generationId: h.generationId, resultPart: "HASHTAGS", kind: "COPIED", surface: "DASHBOARD" })} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </AsyncBlock>
      <h3 className="mb-2 mt-5 t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>Compliance summary (stored checks only)</h3>
      <AsyncBlock a={comp} label="compliance summary" isEmpty={(d) => !d.counts || d.counts.length === 0} empty="No stored validation results to summarise yet.">
        {(d) => (
          <ul className="flex flex-col gap-1.5">
            {d.counts!.map((c) => (
              <li key={c.label} className="t-body-sm" style={{ color: "var(--text-3)" }}>
                <strong style={{ color: "var(--text-1)" }}>{c.count}</strong> {c.label} <span style={{ color: "var(--text-7)" }}>({c.basis})</span>
              </li>
            ))}
          </ul>
        )}
      </AsyncBlock>
      <p className="mt-4 t-meta" style={{ color: "var(--text-7)" }}>Recommend-only: nothing here is sent to a marketplace, and this summary is not a marketplace approval.</p>
    </SectionCard>
  );
}
