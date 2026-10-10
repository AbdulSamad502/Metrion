"use client";

import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Presentation } from "@/lib/ceo";
import { asOfLabel, registerView } from "@/lib/ceoModel";

/** One verified result as the seller sees it: the figures (each with its register and as-of date), the facts, what could not be checked, and
 * what the seller could ask next. Every string here is the backend's own snapshot, shown verbatim: the UI never computes, rounds or
 * re-formats a figure, and a figure the backend could not verify never reaches this component (it arrives as a gap instead). */
export function PresentationView({ presentation, compact = false }: { presentation: Presentation; compact?: boolean }) {
  const { figures, facts, gaps, offers } = presentation;
  const conflicts = presentation.conflicts ?? [];
  const artefacts = presentation.artefacts ?? [];
  return (
    <div className="flex flex-col gap-2" data-testid="presentation">
      {artefacts.map((a) => (
        <section key={a.title} data-testid="artefact" aria-label={a.title} className="rounded-lg px-3 py-2.5" style={{ border: "1px solid var(--border-subtle)", background: "var(--fill-hover)" }}>
          <h4 className="m-0 mb-1 t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>{a.title}</h4>
          <ol className="m-0 flex list-decimal flex-col gap-1 pl-5">
            {a.items.map((text, i) => (
              <li key={`${i}-${text}`} className="t-body-sm" style={{ color: "var(--text-1)" }}>{text}</li>
            ))}
          </ol>
          {a.note && <p className="m-0 mt-1.5 t-meta" style={{ color: "var(--text-5)" }}>{a.note}</p>}
          <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-6)" }}>Written by the specialist from the details you gave. Read it before you use it; Metrion has not checked it against your marketplace account.</p>
        </section>
      ))}
      {conflicts.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Values that disagree">
          {conflicts.map((c) => (
            <li key={c.refIds.join("-")} data-testid="conflict" className="rounded-lg px-2.5 py-2 t-body-sm" style={{ color: "var(--text-2)", border: "1px solid var(--warning-border)" }}>
              {/* the backend's own block, verbatim: both values, their sources and dates, and that neither was chosen */}
              {c.text}
            </li>
          ))}
        </ul>
      )}
      {figures.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Verified figures">
          {figures.map((f) => {
            const reg = registerView(f.register);
            const asOf = asOfLabel(f.as_of);
            return (
              <li key={`${f.ref.kind}-${f.ref.id}-${f.label}`} data-testid="figure" className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="t-body-sm" style={{ color: "var(--text-3)" }}>
                  {f.label}
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  <span data-testid="figure-value" className={compact ? "t-body font-semibold" : "t-card-title font-semibold"} style={{ color: "var(--text-1)" }}>
                    {f.value}
                  </span>
                  <StatusBadge tone={reg.tone}>{reg.label}</StatusBadge>
                  {asOf && (
                    <span className="t-meta" style={{ color: "var(--text-5)" }}>
                      {asOf}
                    </span>
                  )}
                </span>
                {f.note && (
                  <span className="basis-full t-meta" style={{ color: "var(--text-5)" }}>
                    {f.note}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {facts.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="Facts">
          {facts.map((f, i) => (
            <li key={`${f.label}-${i}`} className="t-body-sm" style={{ color: "var(--text-3)" }}>
              <span className="font-semibold" style={{ color: "var(--text-2)" }}>
                {f.label}:
              </span>{" "}
              {f.text}
            </li>
          ))}
        </ul>
      )}
      {gaps.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0" aria-label="What could not be checked">
          {gaps.map((g, i) => (
            <li key={i} className="t-body-sm" style={{ color: "var(--warning)" }}>
              {g}
            </li>
          ))}
        </ul>
      )}
      {offers.length > 0 && (
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" aria-label="You could also ask">
          {offers.map((o) => (
            <li key={o.key} className="t-meta rounded-lg px-2 py-0.5" style={{ color: "var(--text-4)", border: "1px solid var(--border-subtle)" }}>
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
