"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";

type Held = { id: string; rowNumber: number; kind: string; rule: string; reason: string; earlierRow: number | null; values: Record<string, string>; resolution: string | null; resolutionNote: string | null };
type HeldResponse = { items: Held[]; page: number; pageSize: number; total: number; pageCount: number; unresolved: number };

const ACTION_TEXT: Record<string, string> = { KEEP_EARLIER: "You kept the earlier data", DISCARD: "You discarded this row" };

/** Rows an upload held back. They are in no figure. You can keep the earlier data or discard the held row; replacing earlier data and keeping both are not available yet,
 * and this says so rather than offering a button that does nothing. */
export function HeldRows({ jobId }: { jobId: string }) {
  const { getToken } = useAuth();
  const canAdjust = useCanAdjust();
  const [status, setStatus] = useState<"HELD" | "RESOLVED">("HELD");
  const [page, setPage] = useState(1);
  const state = useCfoData<HeldResponse>(`/jobs/${jobId}/held`, `status=${status}&page=${page}&page_size=20`);
  const [error, setError] = useState<string | null>(null);

  const resolve = async (id: string, action: "KEEP_EARLIER" | "DISCARD") => {
    setError(null);
    try {
      await apiFetch(`/api/v1/cfo/jobs/${jobId}/held/resolve`, await getToken(), { method: "POST", body: JSON.stringify({ held_row_ids: [id], action }) });
      state.reload();
    } catch (e) {
      setError(friendlyApiError(e, "That decision could not be saved"));
    }
  };

  return (
    <section aria-label="Held rows" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="t-label">Held rows</h3>
        <span className="flex gap-2 t-meta">
          <button type="button" aria-pressed={status === "HELD"} onClick={() => { setStatus("HELD"); setPage(1); }}>
            Waiting for you
          </button>
          <button type="button" aria-pressed={status === "RESOLVED"} onClick={() => { setStatus("RESOLVED"); setPage(1); }}>
            Decided
          </button>
        </span>
      </div>
      {error && <ErrorNotice message={error} />}
      <SectionState state={state} title="held rows">
        {(d) =>
          d.items.length === 0 ? (
            <p className="t-body">{status === "HELD" ? "No rows are waiting for your decision." : "No decisions yet."}</p>
          ) : (
            <>
              <p className="t-meta" style={{ color: "var(--text-5)" }}>
                {d.unresolved > 0 ? `${d.unresolved} held — needs your decision. Held rows are not counted anywhere.` : "Nothing is waiting for you."}
              </p>
              <ul className="flex flex-col gap-3">
                {d.items.map((h) => (
                  <li key={h.id} className="flex flex-col gap-2 rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
                    <div className="t-body">
                      Row {h.rowNumber}
                      {h.earlierRow ? ` (repeats row ${h.earlierRow})` : ""} — {h.reason}
                    </div>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 t-meta">
                      {Object.entries(h.values).map(([k, v]) => (
                        <div key={k} className="contents">
                          <dt>{k}</dt>
                          <dd>{v}</dd>
                        </div>
                      ))}
                    </dl>
                    {h.resolution ? (
                      <div className="t-meta">{ACTION_TEXT[h.resolution] ?? h.resolution}{h.resolutionNote ? ` — ${h.resolutionNote}` : ""}</div>
                    ) : canAdjust ? (
                      <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={() => resolve(h.id, "KEEP_EARLIER")}>
                          Keep the earlier data
                        </button>
                        <button type="button" onClick={() => resolve(h.id, "DISCARD")}>
                          Discard this row
                        </button>
                      </div>
                    ) : (
                      <div className="t-meta">Held — needs a decision from someone who can change financial data.</div>
                    )}
                  </li>
                ))}
              </ul>
              {d.pageCount > 1 && (
                <nav className="flex gap-2 t-meta" aria-label="Held rows pages">
                  <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                    Previous
                  </button>
                  <button type="button" disabled={page >= d.pageCount} onClick={() => setPage(page + 1)}>
                    Next
                  </button>
                </nav>
              )}
              <p className="t-meta" style={{ color: "var(--text-5)" }}>
                Replacing earlier data with this row, or keeping both, is not available yet.
              </p>
            </>
          )
        }
      </SectionState>
    </section>
  );
}
