"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { PnlInputs } from "@/components/pnl/PnlInputs";
import { PnlResults } from "@/components/pnl/PnlResults";
import { PnlWhatIf } from "@/components/pnl/PnlWhatIf";
import { PNL_MARKETPLACES } from "@/lib/pnlFeeFields";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { formatBps, formatPaise, paiseToInputText } from "@/lib/pnlText";
import { buildRequest, emptyForm, exampleForm, type PnlForm, type PnlScenarioResponse } from "@/lib/pnlScenario";

/** The Profit Calculator. It owns only the form and the last response: every figure comes from `POST /api/v1/cfo/pnl-scenario` (Brain 1) and is
 * rendered as returned. Nothing here is stored, sent to Full CFO, or added to any total (calculator.md §14: a hypothetical is never a verified result). */
export function PnlWorkspace() {
  const { getToken } = useAuth();
  const [form, setFormState] = useState<PnlForm>(() => emptyForm());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<PnlScenarioResponse | null>(null);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setForm = (update: (f: PnlForm) => PnlForm) => {
    setFormState(update);
    setStale(true);
  };

  const reset = () => {
    setFormState((f) => ({ ...emptyForm(f.marketplace), mode: f.mode })); // clears every number, keeps the marketplace and detail level being worked in
    setErrors({});
    setError(null);
    setResult(null);
    setStale(false);
  };

  /** The example form: made-up numbers, labelled as such, replacing what was typed. It keeps the chosen marketplace and shows the Expected (key numbers) view, which is what the example fills in. */
  const loadExample = () => {
    setFormState((f) => exampleForm(f.marketplace));
    setErrors({});
    setError(null);
    setResult(null);
    setStale(false);
  };

  /** "Use this price" copies a solved price into the selling-price field. The result is then out of date until the seller calculates again. */
  const usePrice = (paise: string) => {
    const text = paiseToInputText(paise);
    if (text === "") return;
    setForm((f) => ({ ...f, sellingPrice: { text, na: false } }));
  };

  const calculate = async () => {
    const built = buildRequest(form);
    if (!built.ok) {
      setErrors(built.errors);
      setError("Some numbers could not be read. Fix the highlighted fields, then calculate again.");
      return;
    }
    setErrors({});
    setError(null);
    setBusy(true);
    try {
      const res = await apiFetch<PnlScenarioResponse>("/api/v1/cfo/pnl-scenario", await getToken(), { method: "POST", body: JSON.stringify(built.body) });
      setResult(res);
      setStale(false);
    } catch (e) {
      setError(friendlyApiError(e, "The estimate could not be worked out. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const kept = result?.perKept ?? null;
  const marginBps = result?.metrics?.contributionMarginBps ?? null;
  const marketplaceLabel = PNL_MARKETPLACES.find((m) => m.id === form.marketplace)?.label ?? "";

  return (
    <div className="flex flex-col" style={{ gap: "var(--ov-gap, 24px)" }}>
      <div className="mt-no-print ov-card min-w-0">
        <PnlInputs form={form} setForm={setForm} errors={errors} onReset={reset} onExample={loadExample} />
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" onClick={calculate} disabled={busy} className="mt-btn mt-focus min-h-10 rounded-xl px-6 t-body font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
            {busy ? "Calculating…" : "Calculate"}
          </button>
        </div>
        {error && <div className="mt-4"><ErrorNotice message={error} /></div>}
      </div>
      <div id="pnl-results" className="min-w-0 scroll-mt-24">
        <div className="mt-print-area ov-card flex flex-col gap-4">
          <p className="mt-print-only m-0 t-body-sm">Metrion profit &amp; loss estimate · {marketplaceLabel} · {form.mode === "quick" ? "Expected" : "Detailed"} · hypothetical estimate, not verified</p>
          <PnlResults result={result} stale={stale} busy={busy} onUsePrice={usePrice} />
          <div className="mt-no-print">
            <button type="button" onClick={() => window.print()} disabled={!result || result.status === "incomplete"} className="mt-btn mt-focus min-h-10 rounded-lg px-4 t-body-sm font-semibold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
              Print or save as PDF
            </button>
          </div>
        </div>
      </div>
      <div className="mt-no-print ov-card"><PnlWhatIf form={form} hasResult={result !== null && result.status !== "incomplete"} /></div>
      {kept && result && result.status !== "incomplete" && (
        <a href="#pnl-results" aria-label="Jump to your result" className="mt-no-print fixed inset-x-3 bottom-3 z-30 flex items-center justify-between rounded-2xl px-4 py-3 shadow-2xl lg:hidden" style={{ background: "var(--bg-popover)", border: "1px solid var(--accent-border-strong)", color: "var(--text-1)" }} data-testid="glance-bar">
          <span className="t-body-sm" style={{ color: "var(--text-5)" }}>{result.status === "provisional" ? "Profit before missing costs" : "Profit per order kept"}</span>
          <span className="t-headline font-semibold tabular-nums" style={{ color: kept.contribution.startsWith("-") ? "var(--negative)" : "var(--accent)" }}>
            {formatPaise(kept.contribution)}
            {marginBps !== null && <span className="ml-2 t-meta" style={{ color: "var(--text-5)" }}>{formatBps(marginBps)}</span>}
          </span>
        </a>
      )}
    </div>
  );
}
