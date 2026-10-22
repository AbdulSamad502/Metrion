"use client";

import { useId, useState } from "react";
import type { FigureData } from "@/lib/cfoV2/types";

/** "Where does this number come from?" — a keyboard-operable disclosure (a button, not hover) listing source, freshness, formula, exclusions and missing inputs. */
export function TrustPopover({ figure, onProvide }: { figure: FigureData; onProvide?: (dataRequestId: string | null | undefined) => void }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const ref = figure.engineResultRef ?? figure.estimateRef ?? null;
  return (
    <div className="relative inline-block">
      <button type="button" className="t-meta underline" style={{ color: "var(--text-5)" }} aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
        Why this figure?
      </button>
      {open && (
        <div id={panelId} role="region" aria-label={`How ${figure.label} was produced`} className="mt-2 flex flex-col gap-2 rounded-lg p-3 t-meta" style={{ background: "var(--fill-hover)", color: "var(--text-3)" }}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {figure.source.length > 0 && (
              <>
                <dt>Source</dt>
                <dd>{figure.source.map((s) => s.label).join(", ")}</dd>
              </>
            )}
            {figure.lastUpdated && (
              <>
                <dt>Last updated</dt>
                <dd>{figure.lastUpdated}</dd>
              </>
            )}
            {figure.periodCoverage && (
              <>
                <dt>Covers</dt>
                <dd>{figure.periodCoverage}</dd>
              </>
            )}
            {figure.asOfDate && (
              <>
                <dt>As of</dt>
                <dd>{figure.asOfDate}</dd>
              </>
            )}
            {ref && (
              <>
                <dt>{figure.engineResultRef ? "Calculation reference" : "Estimate reference"}</dt>
                <dd>{ref}</dd>
              </>
            )}
            {figure.formulaVersion && (
              <>
                <dt>Formula version</dt>
                <dd>{figure.formulaVersion}</dd>
              </>
            )}
          </dl>
          {figure.exclusions.length > 0 && (
            <div>
              <div className="t-label">Left out</div>
              <ul className="list-disc pl-5">
                {figure.exclusions.map((x) => (
                  <li key={x.reason}>
                    {x.reason}: {x.count}
                    {x.amountDisplay ? ` (${x.amountDisplay})` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {figure.missingInputs.length > 0 && (
            <div>
              <div className="t-label">Missing inputs</div>
              <ul className="list-disc pl-5">
                {figure.missingInputs.map((m) => (
                  <li key={m.field}>
                    {m.why}
                    {onProvide && (
                      <button type="button" className="ml-2 underline" onClick={() => onProvide(m.dataRequestId)}>
                        Provide this
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
