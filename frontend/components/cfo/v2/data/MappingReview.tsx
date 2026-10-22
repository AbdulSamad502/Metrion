"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { TAX_CHOICES, hasError, needsDecision, refusalReasons, type ConfirmBody, type FieldEdit, type MappingField, type MappingView } from "@/lib/cfoV2/mapping";

const GST_INCLUSIVE_NOTE =
  "Heads up: an amount that includes GST cannot be used yet. If you confirm it, this file will be refused with a clear reason rather than read wrongly.";

/** Review the columns Metrion proposed for an upload. Every field shows what the column was read as and the validator's evidence. A field with reasons to double-check needs
 * an explicit "I confirm this" — leaving it alone is never confirmation. Tax inclusion and sign can be corrected. Nothing is saved until the seller confirms, and a refusal
 * lists every reason, changing nothing. */
export function MappingReview({ jobId, onConfirmed }: { jobId: string; onConfirmed?: () => void }) {
  const { getToken } = useAuth();
  const [view, setView] = useState<MappingView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Record<number, boolean>>({});
  const [edits, setEdits] = useState<Record<number, FieldEdit>>({});
  const [reasons, setReasons] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const v = await apiFetch<MappingView>(`/api/v1/cfo/jobs/${jobId}/mapping`, await getToken());
        if (alive) setView(v);
      } catch (e) {
        if (alive) setLoadError(friendlyApiError(e, "Could not load the proposed columns"));
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (loadError) return <ErrorNotice message={loadError} />;
  if (!view) return <p role="status">Loading the proposed columns…</p>;

  const effectiveTax = (f: MappingField) => edits[f.index]?.tax_inclusion ?? f.taxInclusion;
  const setEdit = (i: number, patch: FieldEdit) => setEdits((cur) => ({ ...cur, [i]: { ...cur[i], ...patch } }));
  const blocked = view.fields.some((f) => hasError(f));

  const confirm = async () => {
    setBusy(true);
    setError(null);
    setReasons([]);
    const body: ConfirmBody = { decisions: {}, overrides: {} };
    for (const f of view.fields) {
      if (confirmed[f.index]) body.decisions[String(f.index)] = "SELLER_CONFIRMED";
      if (edits[f.index]) body.overrides[String(f.index)] = edits[f.index];
    }
    try {
      await apiFetch(`/api/v1/cfo/jobs/${jobId}/mapping/confirm`, await getToken(), { method: "POST", body: JSON.stringify(body) });
      onConfirmed?.();
    } catch (e) {
      const list = refusalReasons(e);
      if (list) setReasons(list);
      else setError(friendlyApiError(e, "The columns could not be confirmed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Review the columns" className="flex flex-col gap-4">
      <p className="t-body">Check what each column was read as. Nothing is saved until you confirm.</p>
      <ul className="flex flex-col gap-3">
        {view.fields.map((f) => (
          <li key={f.index} className="flex flex-col gap-1 rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
            <div className="t-body">
              <strong>{f.sourceColumn}</strong> → {f.canonicalField ?? "not used"}
              {f.componentCode ? ` (${f.componentCode})` : ""}
            </div>
            {(f.evidence?.errors ?? []).map((x) => (
              <div key={x.rule + x.message} role="alert" className="t-meta" style={{ color: "var(--negative)" }}>
                Problem: {x.message}
              </div>
            ))}
            {(f.evidence?.warnings ?? []).map((x) => (
              <div key={x.rule + x.message} className="t-meta" style={{ color: "var(--warning)" }}>
                Warning: {x.message}
              </div>
            ))}
            {f.taxInclusion !== null || edits[f.index]?.tax_inclusion ? (
              <label className="flex items-center gap-2 t-meta">
                GST on this amount
                <select value={effectiveTax(f) ?? ""} onChange={(e) => setEdit(f.index, { tax_inclusion: e.target.value })}>
                  <option value="" disabled>
                    Choose…
                  </option>
                  {TAX_CHOICES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {effectiveTax(f) === "INCLUSIVE" && (
              <div role="note" className="t-meta" style={{ color: "var(--warning)" }}>
                {GST_INCLUSIVE_NOTE}
              </div>
            )}
            {needsDecision(f) && (
              <div className="flex flex-col gap-1">
                {(f.evidence?.confirm_reasons ?? []).map((r) => (
                  <div key={r} className="t-meta">
                    Please check: {r}
                  </div>
                ))}
                <label className="flex items-center gap-2 t-meta">
                  <input type="checkbox" checked={!!confirmed[f.index]} onChange={(e) => setConfirmed((c) => ({ ...c, [f.index]: e.target.checked }))} />
                  I confirm {f.sourceColumn} is read correctly
                </label>
              </div>
            )}
          </li>
        ))}
      </ul>
      {reasons.length > 0 && (
        <div role="alert" className="flex flex-col gap-1 rounded-lg p-3 t-body" style={{ background: "var(--negative-fill)", color: "var(--negative)" }}>
          <div>The columns cannot be confirmed yet. Nothing was changed.</div>
          <ul className="list-disc pl-5">
            {reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {error && <ErrorNotice message={error} />}
      <button type="button" onClick={confirm} disabled={busy || blocked}>
        {busy ? "Confirming…" : "Confirm these columns"}
      </button>
      {blocked && <p className="t-meta">Fix the problems above in your file and upload it again.</p>}
    </section>
  );
}
