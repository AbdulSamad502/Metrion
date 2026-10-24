"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Section } from "@/components/ui/Section";
import { useToast } from "@/components/ui/Toast";
import { ApiError, apiFetch, type UploadOutcome, type ManualAdjustmentIdResponse } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { ErrorText, Field, FileInput, SubmitButton, TextInput, PeriodPresets } from "@/components/cfo/primitives";

// --- Ingestion, seller goal, financial health, strategic briefing (cfo-agent.md §6.16/§7.5) --

export function IngestUploadSection({
  getToken,
  onUploaded,
}: {
  getToken: () => Promise<string | null>;
  onUploaded: (outcome: UploadOutcome) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [marketplace, setMarketplace] = useState("MEESHO");
  const [adapterId, setAdapterId] = useState("meesho.orders.v1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const submit = async () => {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const token = await getToken();
      const form = new FormData();
      form.append("file", file);
      const qs = new URLSearchParams({ marketplace, adapter_id: adapterId }).toString();
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? ""}/api/v1/cfo/ingest?${qs}`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: form,
      });
      const json = await res.json().catch(() => null);
      if (!res.ok) throw new ApiError(res.status, json?.detail ?? res.statusText); // never shown raw: friendlyApiError maps it to plain words
      if (!json) throw new Error("empty response");
      setResult(json);
      if (typeof json.reportFileId === "string") {
        onUploaded({ reportFileId: json.reportFileId, duplicate: Boolean(json.duplicate), filename: file.name });
      }
    } catch (e) {
      setError(friendlyApiError(e, "Could not upload the file"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Upload a marketplace report (CSV)">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Marketplace"><TextInput value={marketplace} onChange={setMarketplace} /></Field>
          <Field label="Adapter id (e.g. meesho.orders.v1)"><TextInput value={adapterId} onChange={setAdapterId} /></Field>
          <Field label="File">
            <FileInput accept=".csv" className="t-body-sm w-full min-w-0 max-w-full" style={{ color: "var(--text-4)" }} onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Upload & ingest" busyLabel="Ingesting…" primary /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="t-body-sm" role="status" style={{ color: "var(--text-3)" }}>
            {result.duplicate
              ? "This exact file was already imported — nothing was ingested again. See it in Import history below."
              : `Ingested. ${String(result.rowCountAccepted ?? "?")} of ${String(result.rowCountRead ?? "?")} rows accepted, ${String(result.rowCountRejected ?? 0)} rejected, ${String(result.rowCountDuplicate ?? 0)} duplicates skipped. Open it in Import history below to inspect what was saved.`}
          </div>
        )}
      </div>
    </Section>
  );
}

type SellerGoal = { targetMarginPct: string | null; priorityCategory: string | null; note: string | null };

/** A margin target is sent as a decimal string (spec §7.2.1), never a number: "15", "15.5" or "15.00", between 0 and 100. */
const MARGIN_PATTERN = /^(?:100(?:\.0{1,2})?|\d{1,2}(?:\.\d{1,2})?)$/;

export function SellerGoalSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [targetMarginPct, setTargetMarginPct] = useState("");
  const [priorityCategory, setPriorityCategory] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const [current, setCurrent] = useState<SellerGoal | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // What is stored right now, read from the server (not from what this tab last typed), so a saved goal is visible after a reload.
  const load = async () => {
    try {
      const goal = await apiFetch<SellerGoal>("/api/v1/cfo/seller-goal", await getToken());
      setCurrent(goal);
      setLoadError(null);
    } catch (e) {
      setLoadError(friendlyApiError(e, "Could not load the saved goal"));
    }
  };
  useEffect(() => {
    (async () => {
      await load();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setError(null);
    if (targetMarginPct.trim() && !MARGIN_PATTERN.test(targetMarginPct.trim())) {
      setError("Target margin must be a percentage between 0 and 100, like 15 or 15.50. Nothing was saved.");
      return;
    }
    setBusy(true);
    try {
      await apiFetch<ManualAdjustmentIdResponse>("/api/v1/cfo/seller-goal", await getToken(), {
        method: "PUT",
        body: JSON.stringify({
          target_margin_pct: targetMarginPct.trim() || null,
          priority_category: priorityCategory.trim() || null,
          note: note.trim() || null,
        }),
      });
      await load(); // confirm by reading it back
      toast.success("Goal saved.");
    } catch (e) {
      setError(friendlyApiError(e, "Could not save the goal"));
    } finally {
      setBusy(false);
    }
  };

  const hasGoal = current !== null && (current.targetMarginPct || current.priorityCategory || current.note);

  return (
    <Section title="Your goal" hint="Used only as background for the written summary in the strategic briefing. It does not change any figure.">
      <div className="flex flex-col gap-3">
        <div className="t-body-sm" style={{ color: "var(--text-5)" }} data-testid="current-goal">
          {loadError
            ? loadError
            : current === null
              ? "Loading the saved goal…"
              : hasGoal
                ? `Saved goal: target margin ${current.targetMarginPct ? current.targetMarginPct + "%" : "not set"} · priority ${current.priorityCategory ?? "not set"} · note ${current.note ?? "none"}. Saving replaces it as a whole.`
                : "No goal is saved yet."}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Target margin % (optional)"><TextInput value={targetMarginPct} onChange={setTargetMarginPct} placeholder="e.g. 15" /></Field>
          <Field label="Priority category (optional)"><TextInput value={priorityCategory} onChange={setPriorityCategory} placeholder="e.g. reduce fees" /></Field>
          <Field label="Note (optional)"><TextInput value={note} onChange={setNote} /></Field>
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Save goal" busyLabel="Saving…" /></div>
        <ErrorText>{error}</ErrorText>
      </div>
    </Section>
  );
}


/** The backend's band names and metric codes, in plain words. A band or metric this list does not know is shown exactly as the backend sent it, never guessed. */
const BAND_VIEW: Record<string, { label: string; tone: "accent" | "warning" | "negative" }> = {
  GOOD: { label: "Good", tone: "accent" },
  WATCH: { label: "Watch", tone: "warning" },
  AT_RISK: { label: "At risk", tone: "negative" },
};
const BAND_METRICS: Record<string, string> = { CONTRIBUTION_MARGIN_PCT: "Contribution margin", FEE_RATIO_PCT: "Fee ratio", RETURN_RATE_PCT: "Return rate" };

function HealthBands({ result }: { result: Record<string, unknown> }) {
  const overall = result.overallBand == null ? null : String(result.overallBand);
  const per = Object.entries((result.perMetricBands ?? {}) as Record<string, unknown>);
  const view = (band: string) => BAND_VIEW[band] ?? { label: band, tone: "warning" as const };
  return (
    <div className="flex flex-col gap-3" data-testid="health-bands-result">
      <div className="flex flex-wrap items-center gap-2 t-body" style={{ color: "var(--text-3)" }}>
        <span>Overall</span>
        {overall ? <StatusBadge tone={view(overall).tone} dot>{view(overall).label}</StatusBadge> : <StatusBadge tone="neutral">Not available</StatusBadge>}
        {result.unavailableReason ? <span className="t-body-sm" style={{ color: "var(--text-5)" }}>{String(result.unavailableReason)}</span> : null}
      </div>
      {per.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Band for each measure">
          {per.map(([code, band]) => (
            <li key={code} className="flex flex-wrap items-center justify-between gap-2 t-body-sm" style={{ color: "var(--text-3)" }}>
              <span>{BAND_METRICS[code] ?? code}</span>
              <StatusBadge tone={view(String(band)).tone} dot>{view(String(band)).label}</StatusBadge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FinancialHealthSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const submit = async () => {
    if (!periodStart || !periodEnd || !asOfDate) {
      setError("Fill in all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<Record<string, unknown>>("/api/v1/cfo/financial-health", await getToken(), {
        method: "POST",
        body: JSON.stringify({ period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate }),
      });
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not compute financial health"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Financial health" hint="Rates your saved margin, fee and return figures for a period as Good, Watch or At risk. It uses figures already calculated; nothing new is worked out.">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
          <PeriodPresets onPick={(s, e) => { setPeriodStart(s); setPeriodEnd(e); }} />
        </div>
        <div><SubmitButton onClick={submit} busy={busy} label="Compute" busyLabel="Computing…" /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <HealthBands result={result} />
        )}
      </div>
    </Section>
  );
}

/** The same signal is never listed twice: two signals with the same label, headline, action and detail collapse into one. (The server already merges identical data requests;
 * this keeps the page honest if any other source repeats itself.) Signals that differ in any of those, e.g. the same field missing for two SKUs, are all kept. */
function distinctSignals(signals: Record<string, unknown>[]): Record<string, unknown>[] {
  const seen = new Set<string>();
  return signals.filter((s) => {
    const key = JSON.stringify([s.severityLabel, s.headline, s.recommendedActionType, (s.evidence as { textValue?: unknown } | null)?.textValue ?? null]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function StrategicBriefingSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [asOfDate, setAsOfDate] = useState("");
  const [includeNarration, setIncludeNarration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ signals: Record<string, unknown>[]; narrative: string | null } | null>(null);

  const submit = async () => {
    if (!periodStart || !periodEnd || !asOfDate) {
      setError("Fill in all three dates first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<{ signals: Record<string, unknown>[]; narrative: string | null }>(
        "/api/v1/cfo/strategic-briefing",
        await getToken(),
        {
          method: "POST",
          body: JSON.stringify({
            period_start: periodStart, period_end: periodEnd, as_of_date: asOfDate, include_narration: includeNarration,
          }),
        },
      );
      setResult(res);
    } catch (e) {
      setError(friendlyApiError(e, "Could not build the briefing"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Strategic briefing" hint="Signals found by fixed rules from your saved results. A short written summary is optional.">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <Field label="Period start"><TextInput type="date" value={periodStart} onChange={setPeriodStart} /></Field>
          <Field label="Period end"><TextInput type="date" value={periodEnd} onChange={setPeriodEnd} /></Field>
          <Field label="As-of date"><TextInput type="date" value={asOfDate} onChange={setAsOfDate} /></Field>
          <PeriodPresets onPick={(s, e) => { setPeriodStart(s); setPeriodEnd(e); }} />
        </div>
        <label className="flex min-h-6 items-center gap-2 t-body-sm" style={{ color: "var(--text-6)" }}>
          <input type="checkbox" checked={includeNarration} onChange={(e) => setIncludeNarration(e.target.checked)} />
          Include a written summary (written by a local AI model, so it takes longer)
        </label>
        <div><SubmitButton onClick={submit} busy={busy} label="Build briefing" busyLabel="Building…" /></div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="flex flex-col gap-2">
            {result.signals.length === 0 ? (
              <div style={{ color: "var(--text-6)" }}>No signals for this period.</div>
            ) : (
              distinctSignals(result.signals).map((s, i) => {
                const detail = s.category === "DATA_GAP" ? (s.evidence as { textValue?: string | null } | null)?.textValue : null;
                return (
                  <div key={i} className="t-body-sm" style={{ color: "var(--text-3)" }}>
                    [{String(s.severityLabel)}] {String(s.headline)} — {String(s.recommendedActionType)}
                    {detail ? <span style={{ color: "var(--text-5)" }}> ({detail})</span> : null}
                  </div>
                );
              })
            )}
            {result.narrative && <div className="mt-2 t-body" style={{ color: "var(--text-3)" }}>{result.narrative}</div>}
          </div>
        )}
      </div>
    </Section>
  );
}
