"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { PnlInputs } from "@/components/pnl/PnlInputs";
import { PnlResults } from "@/components/pnl/PnlResults";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { paiseToInputText } from "@/lib/pnlText";
import { buildRequest, emptyForm, type PnlForm, type PnlScenarioResponse } from "@/lib/pnlScenario";

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
    setFormState(emptyForm());
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

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <PnlInputs form={form} setForm={setForm} errors={errors} onReset={reset} />
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button type="button" onClick={calculate} disabled={busy} className="mt-btn mt-focus rounded-xl px-5 py-3 t-body font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
            {busy ? "Calculating…" : "Calculate"}
          </button>
        </div>
        {error && <div className="mt-4"><ErrorNotice message={error} /></div>}
      </div>
      <div className="min-w-0 xl:sticky xl:top-4 xl:self-start">
        <PnlResults result={result} stale={stale} busy={busy} onUsePrice={usePrice} />
      </div>
    </div>
  );
}
