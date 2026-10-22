"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import type { JobView } from "@/lib/cfoV2/ingest";

type Columns = {
  reportKind: string;
  canManuallyMap: boolean;
  columns: { index: number; name: string }[];
  canonicalFields: { name: string; valueType: string }[];
  requiredGroups: string[][];
  transforms: string[];
  taxInclusion: string[];
  signConventions: string[];
  componentCodes: string[];
};
type Choice = { field: string; transform: string; tax: string; sign: string; component: string };
const EMPTY: Choice = { field: "", transform: "", tax: "", sign: "", component: "" };

/** Map the columns yourself when Metrion could not work them out. You choose, for each column you want used, what it is; the choices become a proposal that goes through
 * the same checks and the same explicit confirmation as any other. Nothing from the file is saved before you confirm. */
export function ManualMapping({ jobId, onProposed }: { jobId: string; onProposed: (job: JobView) => void }) {
  const { getToken } = useAuth();
  const [cols, setCols] = useState<Columns | null>(null);
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c = await apiFetch<Columns>(`/api/v1/cfo/jobs/${jobId}/columns`, await getToken());
        if (alive) setCols(c);
      } catch (e) {
        if (alive) setError(friendlyApiError(e, "Could not read this file's columns"));
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (error && !cols) return <ErrorNotice message={error} />;
  if (!cols) return <p role="status">Reading the file&apos;s columns…</p>;
  if (!cols.canManuallyMap) return <p className="t-body">This upload does not need its columns mapped by hand.</p>;

  const chosen = cols.columns.filter((c) => choices[c.index]?.field).map((c) => ({ index: c.index, ...choices[c.index] }));
  const chosenFields = new Set(chosen.map((c) => c.field));
  const missing = cols.requiredGroups.filter((g) => !g.some((f) => chosenFields.has(f)));
  const set = (i: number, patch: Partial<Choice>) => setChoices((cur) => ({ ...cur, [i]: { ...(cur[i] ?? EMPTY), ...patch } }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    const fields = chosen.map((c) => ({
      index: c.index,
      canonical_field: c.field,
      ...(c.transform ? { transform: c.transform } : {}),
      ...(c.tax ? { tax_inclusion: c.tax } : {}),
      ...(c.sign ? { sign_convention: c.sign } : {}),
      ...(c.component ? { component_code: c.component } : {}),
    }));
    try {
      onProposed(await apiFetch<JobView>(`/api/v1/cfo/jobs/${jobId}/mapping/manual`, await getToken(), { method: "POST", body: JSON.stringify({ fields }) }));
    } catch (e) {
      setError(friendlyApiError(e, "The columns could not be proposed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Map the columns yourself" className="flex flex-col gap-4">
      <p className="t-body">Choose what each column is. Leave a column as &ldquo;Not used&rdquo; to ignore it. You will review and confirm before anything is saved.</p>
      <ul className="flex flex-col gap-3">
        {cols.columns.map((c) => {
          const ch = choices[c.index] ?? EMPTY;
          const spec = cols.canonicalFields.find((f) => f.name === ch.field);
          return (
            <li key={c.index} className="flex flex-wrap items-end gap-3 rounded-lg p-3" style={{ background: "var(--fill-hover)" }}>
              <strong className="min-w-[10rem]">{c.name}</strong>
              <label className="flex flex-col gap-1 t-meta">
                Is
                <select aria-label={`What ${c.name} is`} value={ch.field} onChange={(e) => set(c.index, { field: e.target.value })}>
                  <option value="">Not used</option>
                  {cols.canonicalFields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
              {ch.field && (
                <label className="flex flex-col gap-1 t-meta">
                  Read as
                  <select aria-label={`How to read ${c.name}`} value={ch.transform} onChange={(e) => set(c.index, { transform: e.target.value })}>
                    <option value="">As it is</option>
                    {cols.transforms.map((t) => (
                      <option key={t} value={t}>
                        {t.replaceAll("_", " ").toLowerCase()}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {spec?.valueType === "money" && (
                <label className="flex flex-col gap-1 t-meta">
                  GST
                  <select aria-label={`GST on ${c.name}`} value={ch.tax} onChange={(e) => set(c.index, { tax: e.target.value })}>
                    <option value="">Not stated</option>
                    {cols.taxInclusion.map((t) => (
                      <option key={t} value={t}>
                        {t.toLowerCase()}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {ch.field === "component_amount" && (
                <label className="flex flex-col gap-1 t-meta">
                  Component
                  <select aria-label={`Component of ${c.name}`} value={ch.component} onChange={(e) => set(c.index, { component: e.target.value })}>
                    <option value="">Choose…</option>
                    {cols.componentCodes.map((t) => (
                      <option key={t} value={t}>
                        {t.replaceAll("_", " ").toLowerCase()}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </li>
          );
        })}
      </ul>
      {missing.length > 0 && (
        <p role="status" className="t-meta">
          Still needed: {missing.map((g) => g.map((f) => f.replaceAll("_", " ")).join(" or ")).join("; ")}.
        </p>
      )}
      {error && <ErrorNotice message={error} />}
      <button type="button" onClick={submit} disabled={busy || chosen.length === 0 || missing.length > 0}>
        {busy ? "Sending…" : "Use these columns"}
      </button>
    </section>
  );
}
