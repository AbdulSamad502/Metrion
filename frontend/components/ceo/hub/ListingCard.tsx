"use client";

import { useState } from "react";
import type { ListingAuditCheck, ListingAuditFinding, ListingCard as Card } from "@/lib/ceo";

/** The complete, audited listing in the CEO chat (CMO 3.0 M6). It shows only what the backend sent: the listing text with copy buttons, where each researched keyword is used, the audit (checks and
 * findings, every status a word with a mark, never colour alone), the competitor evidence kept apart as "supported" and "consider adding if true", and six SEPARATE states. "Approve for use" is a
 * click bound to this exact saved version; it records the decision in Metrion and nothing else. The card never says a listing is published, live, compliant or accepted by a marketplace, never
 * shows a score for the audit, and when the marketplace rules are not verified it carries the banner the backend sent. A seller's edit is sent as the one fixed sentence the CEO understands
 * ("Change bullet 3 to: ..."), exactly as if they had typed it, so the same checks run. */

const CHECK_WORD: Record<ListingAuditCheck["status"], string> = { PASS: "✓ PASS", FAIL: "✗ FAIL", NOT_ASSESSED: "? NOT ASSESSED", NOT_APPLICABLE: "– NOT APPLICABLE" };
const CHECK_COLOR: Record<ListingAuditCheck["status"], string> = { PASS: "var(--positive)", FAIL: "var(--negative, #E5484D)", NOT_ASSESSED: "var(--text-6)", NOT_APPLICABLE: "var(--text-6)" };
const SEVERITY_WORD: Record<ListingAuditFinding["severity"], string> = { BLOCKER: "✗ MUST FIX", WARNING: "! WARNING", NOTE: "○ NOTE" };
const VERDICT_WORD: Record<Card["audit"]["verdict"], string> = { BLOCKED: "BLOCKED", NEEDS_ATTENTION: "NEEDS ATTENTION", CHECKED_NOT_VERIFIED: "CHECKED, NOT VERIFIED" };
const VERDICT_TEXT: Record<Card["audit"]["verdict"], string> = {
  BLOCKED: "Something must be fixed before you use this text.",
  NEEDS_ATTENTION: "Nothing blocks it, but some things deserve a look.",
  CHECKED_NOT_VERIFIED: "Everything Metrion can check passed, but it was not checked against marketplace rules, and style and grammar are not checked.",
};
const chip = (on: boolean): React.CSSProperties => ({ border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`, background: on ? "var(--fill-hover)" : "transparent", color: on ? "var(--accent)" : "var(--text-3)" });
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const at = (iso: string | null) => (iso ? iso.slice(0, 10) : "");

function Copy({ label, text, onCopied }: { label: string; text: string; onCopied?: () => void }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" aria-label={`Copy ${label}`} className="mt-focus rounded-md px-2 py-0.5 t-meta-sm font-bold" style={chip(done)}
      onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); onCopied?.(); } catch { setDone(false); } }}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}

function Line({ label, text, onCopied }: { label: string; text: string; onCopied?: () => void }) {
  return (
    <li className="flex items-start justify-between gap-2" data-testid={`section-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <span className="min-w-0 flex-1 t-meta" style={{ color: "var(--text-3)" }}><strong style={{ color: "var(--text-2)" }}>{label}:</strong> {text}</span>
      <Copy label={label} text={text} onCopied={onCopied} />
    </li>
  );
}

export function ListingCard({ card, disabled = false, onSend, onApprove, onCopied }: {
  card: Card; disabled?: boolean; onSend: (text: string) => void;
  onApprove?: (generationId: string) => Promise<{ message: string; banner: string | null }>; onCopied?: (generationId: string) => void;
}) {
  const [approved, setApproved] = useState<string | null>(card.states.approvedForUse.done ? card.approveHint : null);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const s = card.sections;
  const blocked = card.audit.verdict === "BLOCKED";
  const copied = () => onCopied?.(card.generationId);
  const byLevel = (lvl: ListingAuditFinding["severity"]) => card.audit.findings.filter((f) => f.severity === lvl);
  const approve = async () => {
    if (!onApprove || busy) return;
    setBusy(true);
    setApproveError(null);
    try { setApproved((await onApprove(card.generationId)).message); } catch { setApproveError("I could not record that. Nothing was changed."); } finally { setBusy(false); }
  };
  return (
    <section data-testid="listing-card" aria-label="Your complete listing" className="mt-2 flex w-full flex-col gap-3 rounded-2xl px-4 py-3.5" style={{ border: "1px solid var(--accent-border-subtle)" }}>
      <div>
        <div className="t-body font-semibold" style={{ color: "var(--text-2)" }}>Your complete {card.marketplace.charAt(0) + card.marketplace.slice(1).toLowerCase()} listing</div>
        <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }} data-testid="listing-notice">{card.notice}</p>
        {card.revisionOf && <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>This is a revised version. The earlier version is still saved.</p>}
      </div>
      {card.banner && <p role="note" data-testid="listing-banner" className="m-0 rounded-lg p-3 t-meta font-bold" style={{ border: "1px solid var(--warning)", color: "var(--warning)" }}>{card.banner}</p>}

      <ul aria-label="Where this version stands" data-testid="listing-states" className="m-0 flex list-none flex-col gap-1 p-0">
        <li className="t-meta" style={{ color: "var(--text-3)" }}>{card.states.generated.done ? "✓" : "○"} Generated{card.states.generated.at ? ` · ${at(card.states.generated.at)}` : ""}</li>
        <li className="t-meta" style={{ color: "var(--text-3)" }}>{card.states.audited.done ? "✓" : "○"} Audited{card.states.audited.verdict ? ` · ${VERDICT_WORD[card.states.audited.verdict as Card["audit"]["verdict"]] ?? card.states.audited.verdict}` : ""}</li>
        <li data-testid="state-approved" className="t-meta" style={{ color: "var(--text-3)" }}>{approved ? "✓" : "○"} Approved for use in Metrion{approved ? "" : " · not yet"}</li>
        <li className="t-meta" style={{ color: "var(--text-3)" }}>{card.states.copied.count > 0 ? "✓" : "○"} Copied · {card.states.copied.count} time{card.states.copied.count === 1 ? "" : "s"}</li>
        <li className="t-meta" style={{ color: "var(--text-3)" }}>{card.states.markedUsed.count > 0 ? "✓" : "○"} Marked as used · {card.states.markedUsed.count} time{card.states.markedUsed.count === 1 ? "" : "s"}</li>
        <li data-testid="state-published" className="t-meta-sm" style={{ color: "var(--text-6)" }}>Published on a marketplace: not tracked. {card.states.published.note}</li>
      </ul>

      <div className="rounded-lg p-3" style={box}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>The listing</div>
        <ul aria-label="Listing text" className="m-0 mt-1 flex list-none flex-col gap-1.5 p-0">
          <Line label="Title" text={s.title} onCopied={copied} />
          {s.bullets.map((b, i) => <Line key={i} label={`Bullet ${i + 1}`} text={b} onCopied={copied} />)}
          <Line label="Description" text={s.description} onCopied={copied} />
          {s.keywords.length > 0 && <Line label="Keywords" text={s.keywords.join(", ")} onCopied={copied} />}
          {s.backend_terms && s.backend_terms.length > 0 && <Line label="Backend terms" text={s.backend_terms.join(", ")} onCopied={copied} />}
        </ul>
        <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>Lengths were measured, not checked against a marketplace rule unless the banner above is absent. {card.strategy !== "NOT_ASSESSED" ? `Title style: ${card.strategy}.` : "Title style: not assessed."}</p>
      </div>

      <div data-testid="keyword-map" className="rounded-lg p-3" style={box}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Where each researched keyword is used</div>
        <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0">
          {card.keywordMap.candidates.map((k) => (
            <li key={k.keyword} className="t-meta" style={{ color: "var(--text-3)" }}>
              <strong style={{ color: "var(--text-2)" }}>{k.keyword}</strong>: {k.placed ? k.where.map((w) => `${w.section.toLowerCase()}${w.count > 1 ? ` ×${w.count}` : ""}`).join(", ") : `not used (${(k.reason ?? "NOT_NEEDED").toLowerCase().replace(/_/g, " ")})`}
            </li>
          ))}
          {card.keywordMap.notUsed.map((k) => <li key={k.keyword} className="t-meta-sm" style={{ color: "var(--text-6)" }}>{k.keyword}: {k.reason}</li>)}
        </ul>
        <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.keywordMap.limits}</p>
      </div>

      <div data-testid="listing-audit" className="rounded-lg p-3" style={box}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Audit</div>
        <p data-testid="audit-verdict" className="m-0 mt-1 t-body" style={{ color: blocked ? "var(--negative, #E5484D)" : "var(--text-2)" }}><strong>{VERDICT_WORD[card.audit.verdict]}.</strong> {VERDICT_TEXT[card.audit.verdict]}</p>
        <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.audit.counts.blockers} must fix · {card.audit.counts.warnings} warnings · {card.audit.counts.notes} notes</p>
        {(["BLOCKER", "WARNING", "NOTE"] as const).map((lvl) => byLevel(lvl).length > 0 && (
          <div key={lvl} data-testid={`findings-${lvl.toLowerCase()}`} className="mt-2">
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label={`${SEVERITY_WORD[lvl]} findings`}>
              {byLevel(lvl).map((f, i) => (
                <li key={`${f.code}-${f.section}-${i}`} className="t-meta" style={{ color: "var(--text-3)" }}>
                  <strong style={{ color: lvl === "BLOCKER" ? "var(--negative, #E5484D)" : "var(--text-2)" }}>{SEVERITY_WORD[lvl]}</strong> · {f.section.toLowerCase().replace(/_/g, " ")}: {f.explanation}
                  {f.correction && <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>Fix: {f.correction}</div>}
                </li>
              ))}
            </ul>
          </div>
        ))}
        <details className="mt-2">
          <summary className="mt-focus t-meta font-bold" style={{ color: "var(--text-3)", cursor: "pointer" }}>All 15 checks</summary>
          <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0">
            {card.audit.checks.map((c) => (
              <li key={c.id} data-testid={`check-${c.id}`} className="t-meta" style={{ color: "var(--text-3)" }}>
                <span style={{ color: CHECK_COLOR[c.status], fontWeight: 700 }}>{CHECK_WORD[c.status]}</span> {c.id} {c.name}
                {c.detail && <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{c.detail}</div>}
              </li>
            ))}
          </ul>
        </details>
        <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.audit.limits}</p>
      </div>

      {card.ci.rows.length > 0 && (
        <div data-testid="listing-ci" className="rounded-lg p-3" style={box}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>What your tracked competitors emphasise</div>
          <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0">
            {card.ci.rows.map((r) => (
              <li key={r.theme} data-testid={`ci-${r.theme}`} className="t-meta" style={{ color: "var(--text-3)" }}>
                <strong style={{ color: "var(--text-2)" }}>{r.theme}</strong> · {r.sharedBy.count} of {r.sharedBy.of} saved competitor listings ·{" "}
                {r.support === "SUPPORTED" ? "✓ matches a detail you confirmed" : "? Consider adding if true for your product (not written into the listing)"}
              </li>
            ))}
          </ul>
          <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.ci.rows[0].limitation}</p>
        </div>
      )}

      <form className="flex flex-wrap items-center gap-2" aria-label="Change one section" onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !disabled) { onSend(draft.trim()); setDraft(""); } }}>
        <label htmlFor="listing-edit" className="sr-only">Change one section of the listing</label>
        <input id="listing-edit" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2500} disabled={disabled} placeholder={card.editHint}
          className="mt-focus rounded-md px-2 py-1 t-meta" style={{ border: "1px solid var(--border-subtle)", background: "transparent", color: "var(--text-2)", minWidth: 240, flex: 1 }} />
        <button type="submit" disabled={disabled || !draft.trim()} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)}>Send change</button>
      </form>

      <div className="flex flex-col gap-1">
        <button type="button" data-testid="approve-for-use" disabled={disabled || busy || blocked || !!approved || !onApprove} onClick={() => void approve()}
          className="mt-focus self-start rounded-md px-3 py-1.5 t-meta font-bold" style={chip(!!approved)}>
          {approved ? "✓ Approved for use" : busy ? "Recording…" : "Approve for use"}
        </button>
        <p data-testid="approve-note" className="m-0 t-meta-sm" style={{ color: approveError ? "var(--negative, #E5484D)" : "var(--text-6)" }}>
          {approveError ?? (approved ? approved : blocked ? "This version has problems that must be fixed first, so it cannot be approved for use." : "This only records your decision in Metrion. It does not publish anything.")}
        </p>
      </div>
    </section>
  );
}
