"use client";

import Link from "next/link";
import { useState } from "react";
import { imageError, SEVERITY_COLOR, SEVERITY_WORD, type ImageCard, type ImagesApi } from "@/lib/cmoImages";

/** Product image quality in the CEO chat (CMO 3.0 M9). It shows only what the backend sent: the score text (or why there is none), each dimension with its points or "not assessed", the findings
 * most important first with why they matter and what to do, the marketplace-rule status (NOT_ASSESSED unless a verified official rule is recorded), and a link to the images page. It measures nothing
 * and makes no request except the "Add to my product images" button on a photo the seller attached in the chat: that button is the only way such a photo joins a product's images. */

const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };

function Attach({ card, api, disabled }: { card: ImageCard; api?: ImagesApi; disabled: boolean }) {
  const pre = card.preselect;
  const [sku, setSku] = useState(pre?.sku ?? "");
  const [marketplace, setMarketplace] = useState<string>(pre?.marketplace ?? "AMAZON");
  const [role, setRole] = useState<string>(pre?.role ?? "SECONDARY");
  const [shot, setShot] = useState<string>(pre?.shotType ?? "OTHER");
  const [state, setState] = useState<{ kind: "idle" } | { kind: "busy" } | { kind: "done"; text: string } | { kind: "error"; text: string }>({ kind: "idle" });
  const att = card.attachment;
  if (!att || !card.investigationId) return null;
  const go = () => {
    if (!api || !sku) return;
    setState({ kind: "busy" });
    api.addFromChat({ sku, marketplace, investigationId: card.investigationId as string, attachmentId: att.id, role: role as "PRIMARY" | "SECONDARY", shotType: shot }).then(
      (r) => setState({ kind: "done", text: r.results[0]?.status === "ACCEPTED" ? "Added to your product images. Nothing was published." : (r.results[0]?.detail ?? "That photo could not be added.") }),
      (e) => setState({ kind: "error", text: imageError(e) }),
    );
  };
  return (
    <div className="flex flex-col gap-2 rounded-lg p-3" style={box} data-testid="image-attach">
      <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Photo “{att.filename}” — not added yet</div>
      <div className="flex flex-wrap items-end gap-2 t-meta">
        <label className="flex flex-col gap-1">Product
          <select aria-label="Product" className="mt-focus rounded-md px-2 py-1" style={box} value={sku} onChange={(e) => setSku(e.target.value)} disabled={disabled}>
            <option value="">Choose a product</option>{(card.products ?? []).map((p) => <option key={p.sku} value={p.sku}>{p.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">Marketplace
          <select aria-label="Marketplace" className="mt-focus rounded-md px-2 py-1" style={box} value={marketplace} onChange={(e) => setMarketplace(e.target.value)} disabled={disabled}>
            {(card.marketplaces ?? []).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">This image is
          <select aria-label="This image is" className="mt-focus rounded-md px-2 py-1" style={box} value={role} onChange={(e) => setRole(e.target.value)} disabled={disabled}>
            <option value="PRIMARY">The main image</option><option value="SECONDARY">An additional image</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">Kind of shot
          <select aria-label="Kind of shot" className="mt-focus rounded-md px-2 py-1" style={box} value={shot} onChange={(e) => setShot(e.target.value)} disabled={disabled}>
            {(card.shotTypes ?? []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
      </div>
      <button type="button" onClick={go} disabled={disabled || !sku || state.kind === "busy" || state.kind === "done"} className="mt-focus self-start rounded-md px-3 py-1.5 t-meta font-bold"
        style={{ border: "1px solid var(--accent)", color: "var(--accent)", background: "transparent" }}>
        {state.kind === "busy" ? "Adding…" : "Add to my product images"}
      </button>
      {state.kind === "done" && <p role="status" className="m-0 t-meta" style={{ color: "var(--positive)" }}>✓ {state.text}</p>}
      {state.kind === "error" && <p role="alert" className="m-0 t-meta" style={{ color: "var(--negative, #E5484D)" }}>{state.text}</p>}
      <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>Typing “yes” does not add it. Nothing is edited or published, and this uses no AI credit.</p>
    </div>
  );
}

export function ImageQualityCard({ card, api, disabled = false, onSend }: { card: ImageCard; api?: ImagesApi; disabled?: boolean; onSend: (text: string) => void }) {
  if (card.view === "ATTACH") return <Attach card={card} api={api} disabled={disabled} />;
  if (card.view === "CLARIFY") {
    return (
      <div className="flex flex-wrap gap-2" data-testid="image-clarify" role="group" aria-label={card.question}>
        {(card.options ?? []).map((o) => (
          <button key={o.label + (o.sku ?? "")} type="button" disabled={disabled} onClick={() => onSend(o.label)} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--accent)", color: "var(--accent)", background: "transparent" }}>{o.label}</button>
        ))}
      </div>
    );
  }
  if (card.view === "EMPTY" || card.view === "REFUSED") {
    return (
      <div className="rounded-lg p-3 t-meta" style={box} data-testid="image-empty" data-view={card.view}>
        <p className="m-0" style={{ color: "var(--text-3)" }}>{card.message}</p>
        {card.link && <Link href={card.link} className="mt-focus mt-1 inline-block font-bold" style={{ color: "var(--accent)" }}>Open the images page →</Link>}
      </div>
    );
  }
  const focus = card.focus ?? null;
  const findings = (card.findings ?? []).filter((f) => !focus || f.imageNumber === focus.imageNumber || f.imageNumber === null);
  return (
    <div className="flex flex-col gap-2.5" data-testid="image-quality-card" data-view={card.view}>
      <div className="rounded-lg p-3" style={box}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Image quality · {card.product?.name} · {card.marketplaceName}</div>
        <p data-testid="image-score" className="m-0 mt-1 t-body" style={{ color: "var(--text-2)" }}><strong>{card.scoreText}</strong></p>
        <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>Image quality only. It is not marketplace compliance and not listing readiness.</p>
        {focus && <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-3)" }}>Showing: <strong>{focus.label}</strong></p>}
      </div>
      <ul className="m-0 grid list-none gap-1.5 p-0 sm:grid-cols-2" aria-label="Quality dimensions">
        {(card.dimensions ?? []).map((d) => (
          <li key={d.key} className="rounded-lg p-2.5 t-meta" style={box} data-testid={`dim-${d.key}`} data-state={d.state}>
            <strong style={{ color: "var(--text-2)" }}>{d.label}</strong>
            <div style={{ color: d.state === "NOT_ASSESSED" ? "var(--text-6)" : "var(--text-3)" }}>{d.state === "NOT_ASSESSED" ? "NOT ASSESSED" : d.pointsText}</div>
            {d.reason && <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{d.reason}</div>}
          </li>
        ))}
      </ul>
      {findings.length > 0 ? (
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Findings, most important first">
          {findings.map((f, i) => (
            <li key={i} className="rounded-lg p-3 t-meta" style={box} data-testid="image-finding" data-severity={f.severity}>
              <div><strong style={{ color: SEVERITY_COLOR[f.severity] }}>{SEVERITY_WORD[f.severity]}</strong> · <span style={{ color: "var(--text-3)" }}>{f.imageLabel}</span></div>
              <p className="m-0 mt-0.5" style={{ color: "var(--text-2)" }}><strong>{f.problem}</strong></p>
              <p className="m-0 mt-0.5" style={{ color: "var(--text-3)" }}><strong>Why it matters:</strong> {f.whyItMatters}</p>
              <p className="m-0 mt-0.5" style={{ color: "var(--text-3)" }}><strong>What to do:</strong> {f.recommendation}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="image-no-findings">No issues were found by these checks{focus ? " for this image" : ""}. That is not a statement that the image meets any marketplace requirement.</p>
      )}
      {!focus && (card.moreFindings ?? 0) > 0 && <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.moreFindings} more finding(s) on the images page.</p>}
      {card.view === "MISSING" && (card.missingShots ?? []).length > 0 && (
        <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-3)" }} aria-label="Photos that would help">
          {(card.missingShots ?? []).map((m) => <li key={m.code} data-testid="missing-shot"><strong>{m.problem}.</strong> {m.recommendation} <span className="t-meta-sm" style={{ color: "var(--text-6)" }}>(a suggestion, not a marketplace requirement)</span></li>)}
        </ul>
      )}
      <div className="rounded-lg p-3 t-meta" style={box} data-testid="image-compliance" data-status={card.compliance?.status}>
        <strong style={{ color: "var(--text-2)" }}>{card.marketplaceName} image requirements: {card.compliance?.status === "NOT_ASSESSED" ? "NOT ASSESSED" : card.compliance?.status === "CHECKED_FAILED" ? "a verified rule check FAILED" : "listed verified checks passed"}</strong>
        <p className="m-0 mt-0.5" style={{ color: "var(--text-3)" }}>{card.compliance?.message}</p>
        {(card.compliance?.checks ?? []).map((c, i) => <p key={i} className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{c.result}: {c.rule}{c.imageNumber ? ` (image ${c.imageNumber})` : ""} — source {c.sourceUrl}, checked {c.checkedOn}</p>)}
        <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.compliance?.notAssessed}</p>
      </div>
      {card.link && <Link href={card.link} className="mt-focus self-start t-meta font-bold" style={{ color: "var(--accent)" }}>Open the images page →</Link>}
    </div>
  );
}
