"use client";

import { useId, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { Section } from "@/components/ui/Section";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { formatBps, formatPaise } from "@/lib/pnlText";
import { NO_OVERRIDES, buildCompareRequest, type PnlCompareResponse, type PnlForm, type WhatIfOverrides } from "@/lib/pnlScenario";

const FIELDS: { key: keyof WhatIfOverrides; label: string; unit: "₹" | "%"; detailedOnly?: boolean }[] = [
  { key: "price", label: "New selling price", unit: "₹" },
  { key: "cost", label: "New product cost", unit: "₹" },
  { key: "rto", label: "New RTO rate", unit: "%" },
  { key: "ret", label: "New return rate", unit: "%" },
  { key: "ads", label: "New ad spend / month", unit: "₹", detailedOnly: true },
];

const money = (v: string | null | undefined) => formatPaise(v);
const negative = (v: string | null) => v !== null && v.startsWith("-");

function Box({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl p-3" style={{ border: "1px solid var(--border-default)" }}>
      <p className="m-0 t-label" style={{ color: "var(--text-5)" }}>{label}</p>
      <p className="m-0 mt-1 t-headline font-semibold tabular-nums" style={{ color: tone ?? "var(--text-1)" }}>{value}</p>
      {sub !== undefined && <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{sub}</p>}
    </div>
  );
}

/** "What if...?": try a different price, cost, return rate or ad spend against the current scenario. The current inputs are never changed: the variant is a second
 * scenario worked out by Brain 1 (`POST /api/v1/cfo/pnl-scenario-compare`), and both figures and the change between them are the server's. Both are hypothetical
 * estimates, labelled as such, and neither is saved. */
export function PnlWhatIf({ form, hasResult }: { form: PnlForm; hasResult: boolean }) {
  const { getToken } = useAuth();
  const [ov, setOv] = useState<WhatIfOverrides>(NO_OVERRIDES);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [out, setOut] = useState<{ response: PnlCompareResponse; form: PnlForm } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idBase = useId();
  const detailed = form.mode === "detailed";

  const compare = async () => {
    const built = buildCompareRequest(form, ov);
    if (!built.ok) {
      setErrors(built.errors);
      setError(built.errors._form ?? null);
      return;
    }
    setErrors({});
    setError(null);
    setBusy(true);
    try {
      const response = await apiFetch<PnlCompareResponse>("/api/v1/cfo/pnl-scenario-compare", await getToken(), { method: "POST", body: JSON.stringify(built.body) });
      setOut({ response, form });
    } catch (e) {
      setError(friendlyApiError(e, "The comparison could not be worked out. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const stale = out !== null && out.form !== form;
  const r = out?.response;
  const change = r?.comparison.perKeptChange ?? null;
  const base = r?.base.perKept ?? null;
  const what = r?.whatIf.perKept ?? null;

  return (
    <Section title="What if…?" hint="Type a new value for anything you want to test. Leave a box empty to keep your current number. Order volume is assumed unchanged. Your inputs above are not changed." panel={false}>
      <div className="flex flex-col gap-4 rounded-2xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} data-testid="what-if">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {FIELDS.filter((f) => !f.detailedOnly || detailed).map((f) => {
            const id = `${idBase}-${f.key}`;
            const err = errors[f.key];
            return (
              <div key={f.key}>
                <label htmlFor={id} className="mb-1.5 block t-body-sm font-medium" style={{ color: "var(--text-5)" }}>{f.label}</label>
                <div className="flex items-center gap-1.5">
                  <span aria-hidden className="t-body-sm" style={{ color: "var(--text-6)" }}>{f.unit}</span>
                  <input id={id} inputMode="decimal" autoComplete="off" value={ov[f.key]} placeholder="Keep current" aria-invalid={err ? true : undefined} aria-describedby={err ? `${id}-err` : undefined}
                    onChange={(e) => setOv((o) => ({ ...o, [f.key]: e.target.value }))} className="mt-input w-full rounded-lg px-3 py-2 t-body" />
                </div>
                {err && <p id={`${id}-err`} role="alert" className="mt-1 t-meta" style={{ color: "var(--negative)" }}>{err}</p>}
              </div>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button type="button" onClick={compare} disabled={busy || !hasResult} className="mt-btn mt-focus min-h-10 rounded-lg px-4 t-body-sm font-semibold" style={{ border: "1px solid var(--accent-border-strong)", color: "var(--accent)" }}>
            {busy ? "Comparing…" : "Compare"}
          </button>
          <button type="button" onClick={() => { setOv(NO_OVERRIDES); setErrors({}); setError(null); setOut(null); }} className="mt-btn mt-focus min-h-10 rounded-lg px-3 t-body-sm font-semibold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>Clear</button>
          {!hasResult && <span className="t-meta" style={{ color: "var(--text-6)" }}>Choose Calculate first, so there is a current result to compare with.</span>}
        </div>
        {error && <ErrorNotice message={error} />}
        {stale && <p role="status" className="m-0 t-body-sm" style={{ color: "var(--warning)" }}>You changed an input after this comparison. Choose Compare again to refresh it.</p>}
        {r && (
          <div className="flex flex-col gap-3" data-testid="what-if-result">
            {r.whatIf.status === "incomplete" || !what || !base ? (
              <p role="alert" className="m-0 t-body-sm" style={{ color: "var(--negative)" }}>The changed values are not enough for a result yet. {r.whatIf.issues.find((i) => i.severity === "blocking")?.message ?? ""}</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-3">
                <Box label="Now" value={money(base.contribution)} sub={r.base.metrics?.contributionMarginBps != null ? formatBps(r.base.metrics.contributionMarginBps) : "—"} />
                <Box label="What if" value={money(what.contribution)} sub={r.whatIf.metrics?.contributionMarginBps != null ? formatBps(r.whatIf.metrics.contributionMarginBps) : "—"} />
                <Box
                  label="Change per order kept"
                  value={change === null ? "Not available" : `${negative(change) ? "" : "+"}${money(change)}`}
                  sub={r.comparison.marginChangeBps !== null ? `${negative(r.comparison.marginChangeBps) ? "" : "+"}${formatBps(r.comparison.marginChangeBps)} margin` : undefined}
                  tone={change === null ? "var(--text-5)" : negative(change) ? "var(--negative)" : "var(--accent)"}
                />
              </div>
            )}
            <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>
              Both figures are hypothetical estimates worked out from what you typed; neither is saved or part of your results. References {r.base.estimateRef} and {r.whatIf.estimateRef}.
            </p>
          </div>
        )}
      </div>
    </Section>
  );
}
