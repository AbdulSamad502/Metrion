"use client";

import { useState } from "react";
import { Section } from "@/components/ui/Section";
import { apiFetch, type AnomalyCheckResponse, type CashReconciliationResponse, type CfoPreviewResponse, type DataRequestItem, type PeriodComparisonResponse, type ReconcileResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { CfoMetricResultRow, ErrorText, Field, SubmitButton, TextInput, rupees } from "@/components/cfo/primitives";

// --- 11. Leak Shield / Reconciliation (POST /cfo/reconcile) ---------------------------

export function ReconcileSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [marketplace, setMarketplace] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReconcileResponse | null>(null);

  const submit = async () => {
    if (!marketplace.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in marketplace and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<ReconcileResponse>("/api/v1/cfo/reconcile", await getToken(), {
        method: "POST",
        body: JSON.stringify({ marketplace: marketplace.trim(), period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not run Leak Shield reconciliation"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Leak Shield / Reconciliation">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} placeholder="AMAZON / FLIPKART / MEESHO" /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Run reconciliation" busyLabel="Reconciling…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              run <code>{result.reconciliationRunId.slice(0, 8)}</code> · matches: {result.matchCount} · exceptions:{" "}
              {result.exceptionCount} · ambiguous: {result.ambiguousMatchCount} · missing dates: {result.datesMissingCount}
            </div>
            {result.findings.length === 0 ? (
              result.matchCount + result.exceptionCount + result.ambiguousMatchCount === 0 ? (
                <div role="status" style={{ color: "var(--text-4)" }}>
                  Nothing could be reconciled for {marketplace.trim()} in this period, so this is not a clean result.
                  {result.datesMissingCount > 0
                    ? ` ${result.datesMissingCount} uploaded line(s) have no date, so they could not be placed in the period.`
                    : " No uploaded sales and settlement lines were found for it. Upload both reports for these dates, then run it again."}
                </div>
              ) : (
                <div style={{ color: "var(--text-6)" }}>No leak findings for this period.</div>
              )
            ) : (
              <div className="mt-table-wrap"><table className="mt-table">
                <thead>
                  <tr style={{ color: "var(--text-6)" }}>
                    <th className="pb-2 font-semibold">Category</th>
                    <th className="pb-2 font-semibold">Severity</th>
                    <th className="pb-2 font-semibold">Amount</th>
                    <th className="pb-2 font-semibold">Marketplace</th>
                    <th className="pb-2 font-semibold">Ref</th>
                  </tr>
                </thead>
                <tbody>
                  {result.findings.map((f) => (
                    <tr key={f.leakFindingId} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{f.leakCategory}</td>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{f.severity}</td>
                      <td className="py-2" style={{ color: "var(--text-3)" }}>{rupees(f.amountPaise)}</td>
                      <td className="py-2" style={{ color: "var(--text-5)" }}>{f.marketplace}</td>
                      <td className="py-2" style={{ color: "var(--text-5)" }}><code>{f.engineResultRef.slice(0, 8)}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 11b. Cash reconciliation (POST /cfo/cash-reconciliation) -------------------------

export function CashReconciliationSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [marketplace, setMarketplace] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CashReconciliationResponse | null>(null);

  const submit = async () => {
    if (!marketplace.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in marketplace and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<CashReconciliationResponse>("/api/v1/cfo/cash-reconciliation", await getToken(), {
        method: "POST",
        body: JSON.stringify({ marketplace: marketplace.trim(), period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not run cash reconciliation"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Cash reconciliation">
      <div className="flex flex-col gap-3">
        <p className="t-body-sm m-0" style={{ color: "var(--text-5)" }}>
          Cash received comes from the settlement reports you uploaded. Expected cash, the variance and TDS are shown as unavailable when your reports do not carry what they need; they are never estimated.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} placeholder="AMAZON / FLIPKART / MEESHO" /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Check cash received" busyLabel="Checking…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            <div className="mt-ledger">
              <CfoMetricResultRow label="Cash received" result={result.cashReceived} />
              <CfoMetricResultRow label="Cash expected" result={result.cashExpected} />
              <CfoMetricResultRow label="Variance" result={result.cashVariance} />
              <CfoMetricResultRow label="TCS collected" result={result.tcsCollected} />
              <CfoMetricResultRow label="TDS deducted" result={result.tdsDeducted} />
            </div>
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              Settled within the usual lag: {result.settledWithinLagCount} · unsettled beyond it: {result.unsettledBeyondLagCount} · missing dates: {result.datesMissingCount}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 12. CFO Preview / free-tier gate (POST /cfo/preview) -----------------------------

export function CfoPreviewSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [marketplace, setMarketplace] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CfoPreviewResponse | null>(null);

  const submit = async () => {
    if (!marketplace.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in marketplace and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<CfoPreviewResponse>("/api/v1/cfo/preview", await getToken(), {
        method: "POST",
        body: JSON.stringify({ marketplace: marketplace.trim(), period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not load the CFO preview"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="CFO Preview (free-tier)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Load preview" busyLabel="Loading…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2 t-body" style={{ color: "var(--text-2)" }}>
            <div>
              Headline total: {rupees(result.headlineTotalPaise)}
              {result.headlineEngineResultRef && (
                <span style={{ color: "var(--text-6)" }}> (ref: <code>{result.headlineEngineResultRef.slice(0, 8)}</code>)</span>
              )}
            </div>
            <div>
              Affected SKUs:{" "}
              {result.affectedSkuCountUnavailable
                ? `UNAVAILABLE — ${result.affectedSkuCountUnavailable}`
                : result.affectedSkuCount ?? "—"}
            </div>
            {result.revealedFinding ? (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                {result.revealedFinding.leakCategory} · {result.revealedFinding.severity} ·{" "}
                {rupees(result.revealedFinding.amountPaise)} · SKU: {result.revealedFinding.sku ?? "—"}
              </div>
            ) : (
              <div style={{ color: "var(--text-6)" }}>No leak finding to show in the data uploaded for this period.</div>
            )}
            {result.lockedFindingsCount > 0 && (
              <div style={{ color: "var(--text-6)" }}>{result.lockedFindingsCount} more finding(s) locked — upgrade to see them all.</div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

/** A method that was not run because Metrion has no threshold for it, in words. The code stays visible for anything not listed. */
const CONFIG_GAP_WORDS: Record<string, string> = {
  NO_CONFIG_FOR_METHOD: "no threshold is configured for this method yet, and Metrion does not invent one. It needs to be set in the anomaly configuration first.",
};

// --- 13. Anomaly check (POST /cfo/anomaly-check) ---------------------------------------

export function AnomalyCheckSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [targetRef, setTargetRef] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [includeNarration, setIncludeNarration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnomalyCheckResponse | null>(null);

  const submit = async () => {
    if (!targetRef.trim() || !periodStart || !periodEnd || !asOfDate) {
      setError("Fill in target ref and all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<AnomalyCheckResponse>("/api/v1/cfo/anomaly-check", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          target_ref: targetRef.trim(),
          period_start: periodStart,
          period_end: periodEnd,
          as_of_date: asOfDate,
          include_narration: includeNarration,
        }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not run the anomaly check"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Anomaly Check">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Field label="Target ref (SKU/ACCOUNT/MARKETPLACE)"><TextInput value={targetRef} onChange={setTargetRef} /></Field>
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <label className="flex min-h-6 items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
          <input type="checkbox" checked={includeNarration} onChange={(e) => setIncludeNarration(e.target.checked)} />
          Include narration (calls the local LLM — slower)
        </label>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Run anomaly check" busyLabel="Checking…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            <div className="t-body-sm" style={{ color: "var(--text-5)" }}>
              metric: {result.metric} · series length: {result.seriesLength}
            </div>
            {result.methods.map((m) => (
              <div
                key={m.method}
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <div style={{ color: "var(--text-2)" }}><strong>{m.method}</strong></div>
                {m.flag && (
                  <div style={{ color: m.flag.fired ? "var(--negative)" : "var(--text-3)" }}>
                    {m.flag.fired ? `Fired — severity ${m.flag.severity}, score ${m.flag.score}` : `Not fired — score ${m.flag.score}`}
                  </div>
                )}
                {m.insufficientHistory && (
                  <div style={{ color: "var(--text-6)" }}>Insufficient history — {m.insufficientHistory.reason}</div>
                )}
                {m.zeroVariance && <div style={{ color: "var(--text-6)" }}>Zero variance — {m.zeroVariance.reason}</div>}
                {m.configurationGap && (
                  <div style={{ color: "var(--text-6)" }}>
                    Not run — {CONFIG_GAP_WORDS[m.configurationGap.reason] ?? m.configurationGap.reason}
                  </div>
                )}
              </div>
            ))}
            {result.narration && (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
              >
                {result.narration}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 14. Period comparison / Brain-3 narration (POST /cfo/period-comparison) ----------

export function PeriodComparisonSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [resultAId, setResultAId] = useState("");
  const [resultBId, setResultBId] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PeriodComparisonResponse | null>(null);

  const submit = async () => {
    if (!resultAId.trim() || !resultBId.trim() || !asOfDate) {
      setError("Fill in both engine result refs and an as-of date first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<PeriodComparisonResponse>("/api/v1/cfo/period-comparison", await getToken(), {
        method: "POST",
        body: JSON.stringify({ result_a_id: resultAId.trim(), result_b_id: resultBId.trim(), as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compare these two periods"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Period Comparison (Brain-3 narration)">
      <div className="flex flex-col gap-3">
        <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
          Both ids must be real, already-persisted <code>engineResultRef</code> values for the same metric code — e.g.
          two different periods&apos; Contribution Profit refs copied from the Period P&amp;L section above.
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Result A id (engineResultRef)"><TextInput value={resultAId} onChange={setResultAId} placeholder="UUID" /></Field>
          <Field label="Result B id (engineResultRef)"><TextInput value={resultBId} onChange={setResultBId} placeholder="UUID" /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
        </div>
        <div>
          <SubmitButton onClick={submit} busy={busy} label="Compare periods" busyLabel="Comparing…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="mt-ledger">
            {result.delta ? (
              <CfoMetricResultRow label="Delta" result={result.delta} />
            ) : (
              <div style={{ color: "var(--text-6)" }}>
                No delta — data request raised{result.dataRequestId ? `: ${result.dataRequestId.slice(0, 8)}` : ""}.
              </div>
            )}
            {result.narration && (
              <div
                className="rounded-lg px-3 py-2 t-body-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
              >
                {result.narration}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 15. Data requests (GET /cfo/data-requests) ----------------------------------------

export function DataRequestsSection({
  rows,
  error,
  onReload,
}: {
  rows: DataRequestItem[] | null;
  error: string | null;
  onReload: () => void;
}) {
  return (
    <Section title="Data Requests">
      <div className="flex flex-col gap-3">
        <button type="button" onClick={onReload} className="w-fit t-meta font-semibold" style={{ color: "var(--text-3)" }}>
          Refresh
        </button>
        {error && <div role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>{error}</div>}
        {rows === null ? (
          <div style={{ color: "var(--text-6)" }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: "var(--text-6)" }}>No data requests raised yet.</div>
        ) : (
          <div className="mt-table-wrap"><table className="mt-table">
            <thead>
              <tr style={{ color: "var(--text-6)" }}>
                <th className="pb-2 font-semibold">Requested field</th>
                <th className="pb-2 font-semibold">Reason</th>
                <th className="pb-2 font-semibold">Blocking metric</th>
                <th className="pb-2 font-semibold">Status</th>
                <th className="pb-2 font-semibold">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                  <td className="py-2" style={{ color: "var(--text-3)" }}>{r.requestedField}</td>
                  <td className="py-2" style={{ color: "var(--text-3)" }}>{r.reason ?? "—"}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{r.blockingMetric ?? "—"}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{r.status}</td>
                  <td className="py-2" style={{ color: "var(--text-5)" }}>{new Date(r.createdAt).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </Section>
  );
}
