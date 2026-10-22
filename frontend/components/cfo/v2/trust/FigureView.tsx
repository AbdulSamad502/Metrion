"use client";

import { Card } from "@/components/ui/Card";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import type { FigureData } from "@/lib/cfoV2/types";
import { CompletenessBadge } from "./CompletenessBadge";
import { AD_STATUS_TEXT, COMPLETENESS_VIEW, isConfirmedActual } from "./formatStates";
import { TrustPopover } from "./TrustPopover";

/** The one way a CFO 2.0 figure is drawn. The value is the server's display string, untouched. An unavailable figure shows "—" with its reason and a way to
 * provide the missing input — never 0, never blank. Anything not COMPLETE carries a badge and a one-line reason in words, so it can never pass as a confirmed
 * actual. Completeness (how whole it is) and register (where it came from) are separate and both shown. */
export function FigureView({ figure, onProvide }: { figure: FigureData; onProvide?: (dataRequestId: string | null | undefined) => void }) {
  const unavailable = figure.valueDisplay === null || figure.completeness === "UNAVAILABLE";
  const reason = figure.unavailableReason ?? figure.missingInputs[0]?.why ?? COMPLETENESS_VIEW.UNAVAILABLE.meaning;
  const notes = figure.statusNotes.length > 0 ? figure.statusNotes : isConfirmedActual(figure.completeness) || unavailable ? [] : [COMPLETENESS_VIEW[figure.completeness].meaning];
  return (
    <Card className="p-5" ariaLabel={figure.label}>
      <div className="flex items-start justify-between gap-2">
        <div className="t-label" style={{ color: "var(--text-5)" }}>
          {figure.label}
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          <CompletenessBadge completeness={figure.completeness} />
          <ProvenanceBadge register={figure.register} />
        </div>
      </div>
      <div className="mt-2.5">
        {unavailable ? (
          <>
            <div className="t-metric" style={{ color: "var(--text-6)" }} aria-label={`${figure.label}: not available`}>
              —
            </div>
            <div className="mt-1 t-meta-sm" style={{ color: "var(--text-7)" }}>
              {reason}
            </div>
            {figure.missingInputs.length > 0 && onProvide && (
              <button type="button" className="mt-2 t-meta underline" onClick={() => onProvide(figure.missingInputs[0].dataRequestId)}>
                Provide this
              </button>
            )}
          </>
        ) : (
          <div className="t-metric" style={{ color: isConfirmedActual(figure.completeness) ? "var(--text-1)" : "var(--text-3)" }}>
            {figure.valueDisplay}
          </div>
        )}
      </div>
      {notes.map((n) => (
        <div key={n} className="mt-2 t-meta" style={{ color: "var(--text-5)" }}>
          {n}
        </div>
      ))}
      {figure.adSpendStatus && (
        <div className="mt-2 t-meta" style={{ color: "var(--text-5)" }}>
          {AD_STATUS_TEXT[figure.adSpendStatus]}
        </div>
      )}
      <div className="mt-3">
        <TrustPopover figure={figure} onProvide={onProvide} />
      </div>
    </Card>
  );
}
