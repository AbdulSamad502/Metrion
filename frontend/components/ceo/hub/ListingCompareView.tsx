"use client";

import type { DiffOp, HistoryCompare, KeywordMove, ListItemDiff, TermDiff } from "@/lib/ceo";

/** The exact differences between two saved versions of one listing (CMO 3.0 M7). It shows only what the backend sent. Every change is a word as well as a mark (+ added, − removed, ~ changed,
 * ↕ moved), never colour alone. Nothing here says a version is better, worse, published or live, and performance is shown as "not assessed" unless the backend sent comparable observations. */

const word = (iso: string) => iso.slice(0, 10);
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const STATUS: Record<ListItemDiff["status"], string> = { unchanged: "= Unchanged", reordered: "↕ Moved", modified: "~ Changed", added: "+ Added", removed: "− Removed" };
const MOVE: Record<KeywordMove["result"], string> = { ADDED: "+ Added", REMOVED: "− Removed", RETAINED: "= Kept", MOVED: "↕ Moved" };
const where = (l: string[]) => (l.length ? l.map((x) => x.toLowerCase().replace(/_/g, " ")).join(", ") : "not used");

export function DiffText({ ops }: { ops: DiffOp[] }) {
  return (
    <span data-testid="diff-text">
      {ops.map((o, i) => {
        if (o.op === "equal") return <span key={i}>{o.new} </span>;
        return (
          <span key={i}>
            {o.old && <del aria-label="removed" style={{ textDecoration: "line-through", color: "var(--negative, #E5484D)" }}>{o.old}</del>}{" "}
            {o.new && <ins aria-label="added" style={{ textDecoration: "underline", color: "var(--positive)" }}>{o.new}</ins>}{" "}
          </span>
        );
      })}
    </span>
  );
}

function Terms({ label, d }: { label: string; d: TermDiff }) {
  if (!d.available) return <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{label}: {d.reason === "NOT_USED_BY_THIS_MARKETPLACE" ? "not used by this marketplace" : "not part of these versions"}.</p>;
  if (!d.changed) return <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>{label}: no change{d.retained.length ? ` (${d.retained.length} kept)` : ""}.</p>;
  return (
    <div className="t-meta" style={{ color: "var(--text-3)" }}>
      <strong style={{ color: "var(--text-2)" }}>{label}</strong>
      {d.added.length > 0 && <div>+ Added: {d.added.join(", ")}</div>}
      {d.removed.length > 0 && <div>− Removed: {d.removed.join(", ")}</div>}
      {d.retained.length > 0 && <div>= Kept: {d.retained.join(", ")}</div>}
    </div>
  );
}

function Items({ items }: { items: ListItemDiff[] }) {
  if (items.length === 0) return <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>Nothing saved in either version.</p>;
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
      {items.map((it, i) => (
        <li key={i} className="rounded-md p-2 t-meta" style={box} data-testid={`item-${it.status}`}>
          <strong style={{ color: "var(--text-2)" }}>{STATUS[it.status]}</strong>
          {it.oldPosition != null && it.newPosition != null && it.oldPosition !== it.newPosition ? ` (${it.oldPosition} → ${it.newPosition})` : ""}
          <div style={{ color: "var(--text-3)" }}>{it.status === "modified" && it.diff ? <DiffText ops={it.diff.ops} /> : (it.new ?? it.old)}</div>
        </li>
      ))}
    </ul>
  );
}

export function CompareView({ c }: { c: HistoryCompare }) {
  const changed = Object.entries({ title: c.sectionsChanged.title, bullets: c.sectionsChanged.bullets, description: c.sectionsChanged.description, keywords: c.sectionsChanged.keywords, "backend terms": c.sectionsChanged.backendTerms, hashtags: c.sectionsChanged.hashtags }).filter(([, v]) => v).map(([k]) => k);
  const counts = c.keywordMovement.counts;
  return (
    <div className="flex flex-col gap-3" data-testid="history-compare">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-md p-2 t-meta" style={box}><strong style={{ color: "var(--text-2)" }}>Older: version {c.older.number}</strong><div style={{ color: "var(--text-4)" }}>{word(c.older.createdAt)} · {c.older.sourceText}</div></div>
        <div className="rounded-md p-2 t-meta" style={box}><strong style={{ color: "var(--text-2)" }}>Newer: version {c.newer.number}</strong><div style={{ color: "var(--text-4)" }}>{word(c.newer.createdAt)} · {c.newer.sourceText}</div></div>
      </div>
      {c.swapped && <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>Shown with the earlier version first.</p>}
      {c.identical ? (
        <p role="status" className="m-0 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="compare-identical">These two versions have identical text. Nothing changed.</p>
      ) : (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="compare-changed">Changed: {changed.join(", ")}.</p>
      )}

      <section aria-label="Title" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">Title</h4>
        {c.title.changed ? (
          <>
            <div className="t-meta" style={{ color: "var(--text-3)" }}><DiffText ops={c.title.ops} /></div>
            <div className="t-meta" style={{ color: "var(--text-4)" }}>Length {c.title.oldLength.characters} → {c.title.newLength.characters} characters ({c.title.characterDelta >= 0 ? "+" : "−"}{Math.abs(c.title.characterDelta)}).</div>
            {c.title.attributes.removed.length > 0 && <div className="t-meta" style={{ color: "var(--text-3)" }}>− Confirmed details no longer in the title: {c.title.attributes.removed.map((a) => `${a.attribute}: ${a.value}`).join(", ")}</div>}
          </>
        ) : <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>No change.</p>}
      </section>

      <section aria-label="Bullets" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">Bullets</h4>
        {c.bullets.changed ? <Items items={c.bullets.items.filter((i) => i.status !== "unchanged")} /> : <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>No change ({c.bullets.counts.unchanged ?? 0} unchanged).</p>}
      </section>

      <section aria-label="Description" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">Description</h4>
        {c.description.changed ? (
          <>
            <Items items={c.description.items.filter((i) => i.status !== "unchanged")} />
            {c.description.oldLength && c.description.newLength && <div className="t-meta" style={{ color: "var(--text-4)" }}>Length {c.description.oldLength.characters} → {c.description.newLength.characters} characters.</div>}
          </>
        ) : <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>No change.</p>}
      </section>

      <section aria-label="Keywords and terms" className="flex flex-col gap-1.5">
        <h4 className="m-0 mt-eyebrow">Keywords</h4>
        <Terms label="Keyword list" d={c.keywords} />
        <Terms label="Backend search terms" d={c.backendTerms} />
        <Terms label="Hashtags" d={c.hashtags} />
        {c.keywordMovement.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full t-meta" style={{ borderCollapse: "collapse" }} data-testid="keyword-movement">
              <caption className="sr-only">Where each keyword was and where it is</caption>
              <thead><tr style={{ textAlign: "left", color: "var(--text-5)" }}><th scope="col">Keyword</th><th scope="col">Version {c.older.number}</th><th scope="col">Version {c.newer.number}</th><th scope="col">Result</th></tr></thead>
              <tbody>
                {c.keywordMovement.rows.map((r) => (
                  <tr key={r.keyword} style={{ borderTop: "1px solid var(--border-subtle)", color: "var(--text-3)" }}>
                    <td>{r.keyword}{r.trace.evidence === "UNAVAILABLE" && <span style={{ color: "var(--text-5)" }}> (no saved evidence)</span>}</td>
                    <td>{where(r.before)}</td><td>{where(r.after)}</td><td><strong>{MOVE[r.result]}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-5)" }}>{counts.ADDED} added · {counts.REMOVED} removed · {counts.MOVED} moved · {counts.RETAINED} kept. {c.keywordMovement.limits}</p>
          </div>
        )}
      </section>

      <section aria-label="Audit changes" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">Audit changes</h4>
        {!c.audit.available ? <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>One of these versions has no saved audit, so the audits cannot be compared.</p> : (
          <>
            <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>Verdict: {String(c.audit.olderVerdict).replace(/_/g, " ").toLowerCase()} → {String(c.audit.newerVerdict).replace(/_/g, " ").toLowerCase()}.</p>
            {([["New issues", c.audit.new, "+"], ["Resolved", c.audit.resolved, "✓"], ["Still unresolved", c.audit.unresolved, "!"]] as const).map(([label, rows, mark]) => (
              <div key={label} className="t-meta" style={{ color: "var(--text-3)" }}>
                <strong style={{ color: "var(--text-2)" }}>{mark} {label}: {rows.length}</strong>
                {rows.map((f, i) => <div key={i}>{f.section.toLowerCase()}: {f.explanation}</div>)}
              </div>
            ))}
          </>
        )}
      </section>

      <section aria-label="New claims" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">New claims</h4>
        {!c.claims.available ? <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>The newer version has no saved audit, so new claims cannot be checked.</p>
          : c.claims.new.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--text-4)" }} data-testid="no-new-claims">This revision introduced no claim that your confirmed facts do not support.</p>
          : c.claims.new.map((x, i) => (
            <div key={i} className="rounded-md p-2 t-meta" style={{ border: "1px solid var(--negative, #E5484D)", color: "var(--text-3)" }} data-testid="new-claim">
              <strong style={{ color: "var(--text-2)" }}>✗ {x.section.toLowerCase()}{x.claim ? `: “${x.claim}”` : ""}</strong>
              <div>{x.why} Checked against {x.reference} (audit {x.auditCheck}).</div>
              {x.nextStep && <div>{x.nextStep}</div>}
            </div>
          ))}
      </section>

      <section aria-label="Business performance" className="flex flex-col gap-1">
        <h4 className="m-0 mt-eyebrow">Business performance</h4>
        <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="performance-state">{c.performance.state === "NOT_ASSESSED" ? "Not assessed. " : c.performance.state === "INCOMPARABLE" ? "Cannot be compared. " : "Observed. "}{c.performance.missing ?? c.performance.note}</p>
        <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{c.performance.never}</p>
      </section>
      <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{c.notice}</p>
    </div>
  );
}
