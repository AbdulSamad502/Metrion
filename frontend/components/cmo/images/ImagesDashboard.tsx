"use client";

import { useEffect, useRef, useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { imageError, MARKETPLACE_LABEL, SEVERITY_COLOR, SEVERITY_WORD, type Compliance, type Finding, type ImagePage, type ImagesApi, type Marketplace, type Report, type Role, type ShotType, type StoredImage, type UploadItem } from "@/lib/cmoImages";

/** Product Image Quality Advisor (CMO 3.0 M9). Choose a product and marketplace, upload the seller's own pictures, label the main image and each kind of shot, and review the set. Every score, finding and
 * sentence is computed by the backend from the pictures' pixels with fixed rules (no AI model reads them); this page only shows it. Image quality is not marketplace compliance and not listing
 * readiness. Marketplace requirements are NOT ASSESSED unless a verified official rule is recorded. Nothing is edited, replaced or published, and nothing here uses an AI credit. */

const box: React.CSSProperties = { border: "1px solid var(--ov-line)" };
const ACCEPT = "image/png,image/jpeg,image/webp";
const shotLabel = (shots: ShotType[], key: string) => shots.find((s) => s.key === key)?.label ?? key;
const when = (iso: string) => iso.slice(0, 10);

function scoreText(r: Report): string {
  if (r.scoreState === "COMPLETE") return `${r.score} / 100`;
  if (r.scoreState === "PARTIAL") return `Score withheld: ${r.pointsEarned} of ${r.pointsAssessable} assessable points earned`;
  return "Not calculated";
}

function Thumb({ api, image, alt }: { api: ImagesApi; image: StoredImage; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let url: string | null = null;
    api.file(image.fileUrl).then(
      (u) => {
        url = u;
        if (live) setSrc(u);
        else URL.revokeObjectURL(u);
      },
      () => live && setFailed(true),
    );
    return () => {
      live = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, image.fileUrl]);
  // eslint-disable-next-line @next/next/no-img-element
  return src ? <img src={src} alt={alt} className="h-28 w-28 rounded-md object-contain" style={box} /> : <div className="flex h-28 w-28 items-center justify-center rounded-md t-meta-sm" style={{ ...box, color: "var(--ov-ink-3)" }}>{failed ? "Preview unavailable" : "Loading…"}</div>;
}

type Pending = { id: string; file: File; url: string; role: Role; shotType: string };

function Uploader({ api, sku, marketplace, shots, max, onDone }: { api: ImagesApi; sku: string; marketplace: Marketplace; shots: ShotType[]; max: number; onDone: () => void }) {
  const [pending, setPending] = useState<Pending[]>([]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<UploadItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const urls = useRef<string[]>([]);
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), []);
  const add = (list: FileList | null) => {
    if (!list) return;
    setError(null);
    setResults(null);
    const next: Pending[] = [];
    for (const f of Array.from(list)) {
      if (!ACCEPT.split(",").includes(f.type)) {
        setError(`“${f.name}” is not a PNG, JPEG or WebP picture, so it was left out.`);
        continue;
      }
      const url = URL.createObjectURL(f);
      urls.current.push(url);
      next.push({ id: `${f.name}-${f.size}-${urls.current.length}`, file: f, url, role: "SECONDARY", shotType: "OTHER" });
    }
    setPending((p) => [...p, ...next].slice(0, max));
  };
  const set = (id: string, patch: Partial<Pending>) => setPending((p) => p.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  const primaries = pending.filter((p) => p.role === "PRIMARY").length;
  const go = () => {
    setBusy(true);
    setError(null);
    api.upload(sku, marketplace, pending.map((p) => ({ file: p.file, role: p.role, shotType: p.shotType }))).then(
      (r) => {
        setResults(r.results);
        setPending((p) => p.filter((_, i) => r.results[i]?.status === "REJECTED"));
        setBusy(false);
        onDone();
      },
      (e) => {
        setError(imageError(e));
        setBusy(false);
      },
    );
  };
  return (
    <div className="flex flex-col gap-3" data-testid="image-uploader">
      <label className="flex cursor-pointer flex-col gap-1 rounded-xl p-4 t-meta" style={{ ...box, borderStyle: "dashed" }}>
        <strong style={{ color: "var(--ov-ink-2)" }}>Choose pictures to add (PNG, JPEG or WebP, up to {max} per product)</strong>
        <span style={{ color: "var(--ov-ink-2)" }}>Upload your own product photos only. Nothing is published, and your pictures are stored without location or camera details.</span>
        <input type="file" accept={ACCEPT} multiple aria-label="Choose product pictures" className="mt-focus mt-1" onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </label>
      {pending.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Pictures ready to upload">
          {pending.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-3 rounded-lg p-2.5 t-meta" style={box} data-testid="pending-image">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.url} alt={`Preview of ${p.file.name}`} className="h-16 w-16 rounded-md object-contain" style={box} />
              <span className="min-w-[8rem] flex-1" style={{ color: "var(--ov-ink-2)" }}>{p.file.name}</span>
              <label className="flex flex-col gap-1">This picture is
                <select aria-label={`Role of ${p.file.name}`} className="mt-focus rounded-md px-2 py-1" style={box} value={p.role} onChange={(e) => set(p.id, { role: e.target.value as Role })}>
                  <option value="SECONDARY">An additional image</option><option value="PRIMARY">The main image</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">Kind of shot
                <select aria-label={`Kind of shot for ${p.file.name}`} className="mt-focus rounded-md px-2 py-1" style={box} value={p.shotType} onChange={(e) => set(p.id, { shotType: e.target.value })}>
                  {shots.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </label>
              <button type="button" className="mt-focus rounded-md px-2 py-1 font-bold" style={box} onClick={() => setPending((l) => l.filter((x) => x.id !== p.id))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {primaries > 1 && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-warn)" }}>Only one picture can be the main image. Change the others to additional images.</p>}
      {pending.length > 0 && (
        <button type="button" onClick={go} disabled={busy || primaries > 1} className="mt-focus self-start rounded-md px-3 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--ov-brand-ink)", color: "var(--ov-brand-ink)", background: "transparent" }}>
          {busy ? "Uploading…" : `Upload ${pending.length} picture${pending.length === 1 ? "" : "s"}`}
        </button>
      )}
      {error && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>{error}</p>}
      {results && (
        <ul className="m-0 list-none p-0 t-meta" aria-label="Upload results" role="status">
          {results.map((r, i) => (
            <li key={i} data-testid="upload-result" data-status={r.status} style={{ color: r.status === "ACCEPTED" ? "var(--ov-good)" : "var(--ov-bad)" }}>
              {r.status === "ACCEPTED" ? `✓ ${r.name}: added${r.alreadyStored ? " (you had already uploaded this exact picture)" : ""}` : `✗ ${r.name}: not added. ${r.detail ?? ""}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Gallery({ api, page, onChange }: { api: ImagesApi; page: ImagePage; onChange: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const act = (image: StoredImage, role: Role | "REMOVED", shotType: string) => {
    setBusy(true);
    setError(null);
    api.assign(page.product.sku, page.marketplace, [{ assetId: image.assetId, role, shotType }]).then(
      () => { setBusy(false); onChange(); },
      (e) => { setBusy(false); setError(imageError(e)); },
    );
  };
  if (page.images.length === 0) return <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="gallery-empty">No pictures are attached to this product on {MARKETPLACE_LABEL[page.marketplace]} yet. Missing pictures are never counted as a pass.</p>;
  return (
    <div className="flex flex-col gap-2">
      <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3" aria-label="Product pictures">
        {page.images.map((im, i) => (
          <li key={im.assetId} className="flex gap-3 rounded-xl p-3 t-meta" style={box} data-testid="gallery-image" data-role={im.role}>
            <Thumb api={api} image={im} alt={`Image ${i + 1}: ${shotLabel(page.shotTypes, im.shotType)}`} />
            <div className="flex min-w-0 flex-col gap-1">
              <strong style={{ color: im.role === "PRIMARY" ? "var(--ov-brand-ink)" : "var(--ov-ink-2)" }}>{im.role === "PRIMARY" ? "★ MAIN IMAGE" : "Additional image"} {i + 1}</strong>
              <span style={{ color: "var(--ov-ink-2)" }}>{im.widthPx && im.heightPx ? `${im.widthPx} × ${im.heightPx} px` : "size unknown"}</span>
              <label className="flex flex-col gap-0.5">Kind of shot
                <select aria-label={`Kind of shot for image ${i + 1}`} disabled={busy} className="mt-focus rounded-md px-1.5 py-1" style={box} value={im.shotType} onChange={(e) => act(im, im.role, e.target.value)}>
                  {page.shotTypes.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </label>
              <div className="flex flex-wrap gap-1.5">
                {im.role !== "PRIMARY" && <button type="button" disabled={busy} className="mt-focus rounded-md px-2 py-1 font-bold" style={box} onClick={() => act(im, "PRIMARY", im.shotType)}>Make main image</button>}
                <button type="button" disabled={busy} className="mt-focus rounded-md px-2 py-1 font-bold" style={box} onClick={() => act(im, "REMOVED", im.shotType)}>Remove from product</button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>{error}</p>}
    </div>
  );
}

function ComplianceBox({ c }: { c: Compliance }) {
  return (
    <div className="rounded-xl p-3 t-meta" style={box} data-testid="compliance" data-status={c.status}>
      <strong style={{ color: "var(--ov-ink-2)" }}>{MARKETPLACE_LABEL[c.marketplace]} image requirements: {c.status === "NOT_ASSESSED" ? "NOT ASSESSED" : c.status === "CHECKED_FAILED" ? "a verified rule check FAILED" : "the listed verified checks passed"}</strong>
      <p className="m-0 mt-0.5" style={{ color: "var(--ov-ink-2)" }}>{c.message}</p>
      {c.checks.map((k, i) => (
        <p key={i} className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>{k.result}: {k.rule}{k.imageNumber ? ` (image ${k.imageNumber})` : ""}. Source: {k.source.url}, checked {k.source.checkedOn}, scope {k.source.scope}.</p>
      ))}
      <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>{c.notAssessed}</p>
    </div>
  );
}

function FindingRow({ f, report, shots }: { f: Finding; report: Report; shots: ShotType[] }) {
  const row = f.imageNumber ? report.images.find((i) => i.imageNumber === f.imageNumber) : null;
  const where = row ? `${row.role === "PRIMARY" ? "Main image" : "Additional image"} ${row.imageNumber} (${shotLabel(shots, row.shotType)})` : "Whole image set";
  return (
    <li className="rounded-lg p-3 t-meta" style={box} data-testid="finding" data-severity={f.severity}>
      <div><strong style={{ color: SEVERITY_COLOR[f.severity] }}>{SEVERITY_WORD[f.severity]}</strong> · <span style={{ color: "var(--ov-ink-2)" }}>{where}</span></div>
      <p className="m-0 mt-0.5" style={{ color: "var(--ov-ink-2)" }}><strong>{f.problem}</strong></p>
      <p className="m-0 mt-0.5" style={{ color: "var(--ov-ink-2)" }}><strong>Why it matters to buyers:</strong> {f.whyItMatters}</p>
      <p className="m-0 mt-0.5" style={{ color: "var(--ov-ink-2)" }}><strong>What to improve:</strong> {f.recommendation}</p>
    </li>
  );
}

function Review({ api, page, onChange }: { api: ImagesApi; page: ImagePage; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const r = page.review;
  const run = () => {
    setBusy(true);
    setError(null);
    api.review(page.product.sku, page.marketplace).then(
      () => { setBusy(false); onChange(); },
      (e) => { setBusy(false); setError(imageError(e)); },
    );
  };
  return (
    <div className="flex flex-col gap-3" data-testid="review">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={run} disabled={busy || page.images.length === 0} className="mt-focus rounded-md px-3 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--ov-brand-ink)", color: "var(--ov-brand-ink)", background: "transparent" }}>
          {busy ? "Reviewing…" : r ? "Review these images again" : "Review these images"}
        </button>
        <span className="t-meta" style={{ color: "var(--ov-ink-2)" }}>Free. Measured by fixed rules; no AI model reads your pictures.</span>
      </div>
      {error && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>{error}</p>}
      {!r ? (
        <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-review">{page.images.length === 0 ? "Add pictures first." : "These images have not been reviewed yet."}</p>
      ) : (
        <>
          {!r.isCurrent && <p role="status" className="m-0 t-meta" style={{ color: "var(--ov-warn)" }} data-testid="stale">◆ Your pictures changed after this review ({when(r.createdAt)}). Review them again to update it.</p>}
          <div className="rounded-xl p-4" style={box}>
            <div className="t-meta font-bold" style={{ color: "var(--ov-ink-2)" }}>Overall image quality · reviewed {when(r.createdAt)}</div>
            <strong data-testid="score" className="t-heading" style={{ color: "var(--ov-ink)", fontSize: 24 }}>{scoreText(r.report)}</strong>
            {r.report.scoreState !== "COMPLETE" && <p className="m-0 mt-1 t-meta" style={{ color: "var(--ov-ink-2)" }}>{r.report.scoreState === "PARTIAL" ? "A full score needs every dimension to be assessed. The reasons are listed below; nothing was guessed." : "A score needs a main image."}</p>}
            <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>Image quality only. It is not marketplace compliance and not listing readiness.</p>
          </div>
          <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2 lg:grid-cols-3" aria-label="Quality dimensions">
            {r.report.dimensions.map((d) => (
              <li key={d.key} className="rounded-xl p-3 t-meta" style={box} data-testid={`dimension-${d.key}`} data-state={d.state}>
                <strong style={{ color: "var(--ov-ink-2)" }}>{d.label}</strong>
                <div style={{ color: d.state === "NOT_ASSESSED" ? "var(--ov-ink-3)" : "var(--ov-ink)", fontWeight: 700 }}>{d.state === "NOT_ASSESSED" ? "NOT ASSESSED" : `${d.earned} of ${d.state === "PARTIAL" ? `${d.assessableMax} assessable (max ${d.max})` : d.max}`}</div>
                {d.reason && <div className="t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>{d.reason}</div>}
              </li>
            ))}
          </ul>
          <section aria-label="Findings">
            <h3 className="m-0 mb-1.5 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>What to improve, most important first</h3>
            {r.report.findings.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>No issues were found by these checks. That is not a statement that the images meet any marketplace requirement.</p>
              : <ol className="m-0 flex list-none flex-col gap-1.5 p-0">{r.report.findings.map((f, i) => <FindingRow key={i} f={f} report={r.report} shots={page.shotTypes} />)}</ol>}
          </section>
          <section aria-label="Per-image results">
            <h3 className="m-0 mb-1.5 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>Each image</h3>
            <ul className="m-0 flex list-none flex-col gap-1 p-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>
              {r.report.images.map((im) => (
                <li key={im.imageId} data-testid="per-image">
                  <strong>{im.role === "PRIMARY" ? "Main image" : "Additional image"} {im.imageNumber}</strong> ({shotLabel(page.shotTypes, im.shotType)}, {im.widthPx} × {im.heightPx} px): {Object.entries(im.dimensions).map(([k, v]) => `${k} ${v === null ? "not assessed" : `${v}%`}`).join(" · ")}
                  {im.overlayCheck === "POSSIBLE_OVERLAY" && " · possible text or logo (low-confidence check)"}
                </li>
              ))}
            </ul>
          </section>
          {(r.report.duplicateCheck?.pairs.length ?? 0) > 0 && (
            <section aria-label="Similar pictures">
              <h3 className="m-0 mb-1.5 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>Pictures that look alike</h3>
              <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>
                {r.report.duplicateCheck?.pairs.map((p) => <li key={p.images.join("-")} data-testid="similar-pair" data-verdict={p.verdict}><strong>Images {p.images[0]} and {p.images[1]}: {p.verdict === "REPEAT" ? "look almost the same" : "NOT ASSESSED"}.</strong> {p.reason}</li>)}
              </ul>
            </section>
          )}
          {r.report.missingShots.length > 0 && (
            <section aria-label="Photos that would help">
              <h3 className="m-0 mb-1.5 t-body-sm font-bold" style={{ color: "var(--ov-ink-2)" }}>Photos that would help <span className="t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>(suggestions, not marketplace requirements)</span></h3>
              <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>{r.report.missingShots.map((m) => <li key={m.code} data-testid="missing-shot"><strong>{m.problem}.</strong> {m.recommendation}</li>)}</ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

export function ImagesDashboard({ api, initialSku = "", initialMarketplace = "AMAZON" }: { api: ImagesApi; initialSku?: string; initialMarketplace?: string }) {
  const { data: products, error: pErr } = useLoad(() => api.products(), "products");
  const [sku, setSku] = useState(initialSku);
  const [marketplace, setMarketplace] = useState<Marketplace>((["AMAZON", "FLIPKART", "MEESHO"].includes(initialMarketplace) ? initialMarketplace : "AMAZON") as Marketplace);
  const [tick, setTick] = useState(0);
  const chosen = sku || products?.products[0]?.sku || "";
  const { data: page, error } = useLoad(() => (chosen ? api.page(chosen, marketplace) : Promise.reject(new Error("none"))), `${chosen}|${marketplace}|${tick}`);
  const refresh = () => setTick((n) => n + 1);
  return (
    <div className="cw-page flex flex-col gap-5" data-testid="images-dashboard">
      <SectionCard title="Product image quality" hint="Upload your own product pictures and see how clear, well lit, well framed and consistent they are. Free; nothing is edited or published.">
        {pErr && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>{pErr}</p>}
        {products && products.products.length === 0 && <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-products">No products yet. Tell the CEO about a product in the chat first, then come back to upload its pictures.</p>}
        {products && products.products.length > 0 && (
          <div className="flex flex-wrap items-end gap-3 t-meta">
            <label className="flex flex-col gap-1">Product
              <select aria-label="Product" className="mt-focus rounded-md px-2 py-1.5" style={box} value={chosen} onChange={(e) => setSku(e.target.value)}>
                {products.products.map((p) => <option key={p.sku} value={p.sku}>{p.name}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">Marketplace
              <select aria-label="Marketplace" className="mt-focus rounded-md px-2 py-1.5" style={box} value={marketplace} onChange={(e) => setMarketplace(e.target.value as Marketplace)}>
                {products.marketplaces.map((m) => <option key={m} value={m}>{MARKETPLACE_LABEL[m]}</option>)}
              </select>
            </label>
          </div>
        )}
      </SectionCard>
      {products && products.products.length > 0 && (
        <>
          {error && !page && <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>{error}</p>}
          <SectionCard title="Add pictures" hint="Mark one picture as the main image and say what each other picture shows.">
            <Uploader api={api} sku={chosen} marketplace={marketplace} shots={products.shotTypes} max={products.limits.maxImages} onDone={refresh} />
          </SectionCard>
          {page && (
            <>
              <SectionCard title={`Pictures for ${page.product.name} on ${MARKETPLACE_LABEL[page.marketplace]}`}>
                <Gallery api={api} page={page} onChange={refresh} />
              </SectionCard>
              <SectionCard title="Review" hint="Image quality, kept separate from marketplace compliance and from listing readiness.">
                <Review api={api} page={page} onChange={refresh} />
              </SectionCard>
              <SectionCard title="Marketplace requirements">
                <ComplianceBox c={page.compliance} />
              </SectionCard>
              <SectionCard title="History" hint="Every review is kept. Changes to which pictures belong to this product are recorded too.">
                {page.history.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>No reviews yet.</p> : (
                  <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--ov-ink-2)" }} aria-label="Review history">
                    {page.history.map((h) => <li key={h.id} data-testid="history-row">{when(h.createdAt)} · {h.imageCount} image{h.imageCount === 1 ? "" : "s"} · {h.score === null ? (h.scoreState === "PARTIAL" ? "score withheld" : "not calculated") : `${h.score} / 100`}</li>)}
                  </ul>
                )}
                <details className="mt-2 t-meta" style={{ color: "var(--ov-ink-2)" }}>
                  <summary className="cursor-pointer font-bold">Picture changes ({page.assignmentHistory.length})</summary>
                  <ul className="m-0 mt-1 list-none p-0">{page.assignmentHistory.map((a, i) => <li key={i}>{when(a.at)} · {a.role === "PRIMARY" ? "set as main image" : a.role === "REMOVED" ? "removed from the product" : "set as an additional image"} ({shotLabel(page.shotTypes, a.shotType)})</li>)}</ul>
                </details>
              </SectionCard>
            </>
          )}
        </>
      )}
    </div>
  );
}
