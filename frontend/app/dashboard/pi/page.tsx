"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";
import { useAppSession } from "@/lib/useAppSession";
import {
  ApiError,
  apiFetch,
  type PiCandidate,
  type PiNicheBrief,
  type PiReport,
  type PiReportCandidateEntry,
  type PiRunResult,
  type PiSupplierLookupResponse,
} from "@/lib/api";

/** PI test harness — a real, functional, deliberately undecorated dashboard for clicking
 * through PI's direct-execution routes (`backend/src/backend/api/v1/pi.py`) against the
 * signed-in tenant's own data. Mirrors `dashboard/cfo/page.tsx` and `dashboard/ceo-hub/
 * page.tsx`'s exact conventions (Section, per-form busy/error/result state, a fresh Clerk
 * token per call, money entered/rendered in rupees converted to/from paise at the edge
 * only). No mock data anywhere — every section calls a real backend route and renders
 * exactly what comes back, including genuine UNAVAILABLE/error/empty states.
 *
 * No CEO/CFO agent wiring exists yet (see the PI build plan's Phase 2 scope boundary) —
 * the "final recommendation" section below is therefore an honest, clearly-labeled
 * "not yet available" placeholder, never a faked or partial version of the real thing. */
export default function PiPage() {
  const { session, error: sessionError, displayName, roleLabel } = useAppSession();
  const { getToken } = useAuth();

  const [runId, setRunId] = useState<string | null>(null);
  const [report, setReport] = useState<PiReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportBusy, setReportBusy] = useState(false);

  const reloadReport = async (id: string) => {
    setReportBusy(true);
    setReportError(null);
    try {
      const res = await apiFetch<PiReport>(`/api/v1/pi/report/${id}`, await getToken());
      setReport(res);
    } catch (e) {
      setReportError(e instanceof ApiError ? e.message : "Could not load the PI report");
    } finally {
      setReportBusy(false);
    }
  };

  if (sessionError) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--negative)" }}>
        {sessionError}
      </div>
    );
  }
  if (!session) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--text-5)" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="flex" style={{ background: "var(--bg-base)" }}>
      <Sidebar userName={displayName} roleLabel={roleLabel} active="Products" />
      <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar title="Products" subtitle="Dashboard → Products → Direct-execution routes → Result" />
        <div className="flex-1 overflow-y-auto px-8 py-7">
          <div className="flex flex-col gap-6">
            <NicheBriefSection getToken={getToken} />
            <DiscoverSection
              getToken={getToken}
              runId={runId}
              onRunStarted={(id) => {
                setRunId(id);
                void reloadReport(id);
              }}
              onReload={() => runId && reloadReport(runId)}
              report={report}
              reportBusy={reportBusy}
              reportError={reportError}
            />
            <ShortlistSupplierSection
              getToken={getToken}
              runId={runId}
              report={report}
              onReload={() => runId && reloadReport(runId)}
            />
            <FinalRecommendationSection />
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Shared primitives (same inline CSS-variable convention ceo-hub/cfo pages use) ----

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2.5 text-[16.5px] font-bold" style={{ color: "var(--text-2)" }}>
        {title}
      </div>
      <div className="rounded-xl p-5" style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
        {label}
      </label>
      {children}
    </div>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg px-3 py-2 text-[13px]"
      style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
    />
  );
}

function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg px-3 py-2 text-[13px]"
      style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function SubmitButton({
  onClick,
  busy,
  label,
  busyLabel,
}: {
  onClick: () => void;
  busy: boolean;
  label: string;
  busyLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="w-fit rounded-lg px-4 py-2 text-[13px] font-bold"
      style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 }}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div className="text-[12.5px]" style={{ color: "var(--negative)" }}>
      {children}
    </div>
  );
}

function rupees(paise: number | null): string {
  return paise === null ? "—" : `₹${(paise / 100).toFixed(2)}`;
}

function toPaise(rupeesStr: string): number {
  return Math.round(parseFloat(rupeesStr) * 100);
}

function imageDomain(sourceUrl: string | null): string {
  if (!sourceUrl) return "unknown source";
  try {
    return new URL(sourceUrl).hostname;
  } catch {
    return sourceUrl;
  }
}

// --- 1. Niche brief intake (§6.1 CRUD) ------------------------------------------------

const MARKETPLACE_OPTIONS = ["AMAZON", "FLIPKART", "MEESHO"];

function NicheBriefSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [categoryText, setCategoryText] = useState("");
  const [budget, setBudget] = useState("");
  const [targetMin, setTargetMin] = useState("");
  const [targetMax, setTargetMax] = useState("");
  const [marketplaces, setMarketplaces] = useState<string[]>([]);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdBriefId, setCreatedBriefId] = useState<string | null>(null);

  const toggleMarketplace = (m: string) =>
    setMarketplaces((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m]));

  const createDraft = async () => {
    setCreateBusy(true);
    setCreateError(null);
    setCreatedBriefId(null);
    try {
      const res = await apiFetch<{ nicheBriefId: string }>("/api/v1/pi/niche-briefs", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          category_text: categoryText.trim() || null,
          budget_paise: budget.trim() ? toPaise(budget) : null,
          target_price_min_paise: targetMin.trim() ? toPaise(targetMin) : null,
          target_price_max_paise: targetMax.trim() ? toPaise(targetMax) : null,
          marketplaces: marketplaces.length > 0 ? marketplaces : null,
        }),
      });
      setCreatedBriefId(res.nicheBriefId);
    } catch (e) {
      setCreateError(e instanceof ApiError ? e.message : "Could not create the niche brief draft");
    } finally {
      setCreateBusy(false);
    }
  };

  const [lookupBriefId, setLookupBriefId] = useState("");
  const [lookupBusy, setLookupBusy] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupBrief, setLookupBrief] = useState<PiNicheBrief | null>(null);
  const [lookupNotFound, setLookupNotFound] = useState(false);

  const loadBrief = async () => {
    if (!lookupBriefId.trim()) {
      setLookupError("Enter a niche brief id first.");
      return;
    }
    setLookupBusy(true);
    setLookupError(null);
    setLookupBrief(null);
    setLookupNotFound(false);
    try {
      const res = await apiFetch<PiNicheBrief>(`/api/v1/pi/niche-briefs/${lookupBriefId.trim()}`, await getToken());
      setLookupBrief(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setLookupNotFound(true);
      } else {
        setLookupError(e instanceof ApiError ? e.message : "Could not load the niche brief");
      }
    } finally {
      setLookupBusy(false);
    }
  };

  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const transition = async (action: "mark-ready" | "mark-draft" | "archive") => {
    if (!lookupBrief) return;
    setStatusBusy(true);
    setStatusError(null);
    try {
      await apiFetch(`/api/v1/pi/niche-briefs/${lookupBrief.id}/${action}`, await getToken(), { method: "POST" });
      await loadBrief();
    } catch (e) {
      setStatusError(e instanceof ApiError ? e.message : `Could not ${action.replace("-", " ")} this brief`);
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <Section title="Niche Brief Intake">
      <div className="flex flex-col gap-6">
        <div>
          <div className="mb-2 text-[13px] font-semibold" style={{ color: "var(--text-3)" }}>
            Create a draft
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Category / product idea">
              <TextInput value={categoryText} onChange={setCategoryText} placeholder="e.g. kitchen storage jars" />
            </Field>
            <Field label="Budget (₹)">
              <TextInput value={budget} onChange={setBudget} placeholder="e.g. 50000" />
            </Field>
            <Field label="Target price range (₹)">
              <div className="flex gap-2">
                <TextInput value={targetMin} onChange={setTargetMin} placeholder="min" />
                <TextInput value={targetMax} onChange={setTargetMax} placeholder="max" />
              </div>
            </Field>
          </div>
          <div className="mt-3">
            <div className="mb-1 text-[12.5px]" style={{ color: "var(--text-6)" }}>
              Marketplaces
            </div>
            <div className="flex gap-3">
              {MARKETPLACE_OPTIONS.map((m) => (
                <label key={m} className="flex items-center gap-1.5 text-[13px]" style={{ color: "var(--text-3)" }}>
                  <input type="checkbox" checked={marketplaces.includes(m)} onChange={() => toggleMarketplace(m)} />
                  {m}
                </label>
              ))}
            </div>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={createDraft} busy={createBusy} label="Create draft" busyLabel="Creating…" />
          </div>
          <ErrorText>{createError}</ErrorText>
          {createdBriefId && (
            <div className="mt-1 text-[12.5px]" style={{ color: "var(--accent)" }}>
              Created — niche brief <code>{createdBriefId}</code>. Use it below to mark it READY, then in the
              Discover section.
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
          <div className="mb-2 text-[13px] font-semibold" style={{ color: "var(--text-3)" }}>
            Look up a niche brief
          </div>
          <div className="flex gap-2">
            <TextInput value={lookupBriefId} onChange={setLookupBriefId} placeholder="niche brief id (UUID)" />
            <SubmitButton onClick={loadBrief} busy={lookupBusy} label="Load" busyLabel="Loading…" />
          </div>
          <ErrorText>{lookupError}</ErrorText>
          {lookupNotFound && <div className="mt-1 text-[12.5px]" style={{ color: "var(--text-6)" }}>Not found for this tenant.</div>}
          {lookupBrief && (
            <div className="mt-3 rounded-lg p-3 text-[12.5px]" style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ color: "var(--text-2)" }}>
                <strong>{lookupBrief.category_text ?? "(no category set)"}</strong> — status {lookupBrief.status}
              </div>
              <div style={{ color: "var(--text-5)" }}>
                Budget: {rupees(lookupBrief.budget_paise)} · Target: {rupees(lookupBrief.target_price_min_paise)}–
                {rupees(lookupBrief.target_price_max_paise)} · Marketplaces:{" "}
                {lookupBrief.marketplaces?.join(", ") ?? "none set"}
              </div>
              <div className="mt-2 flex gap-2">
                <SubmitButton onClick={() => transition("mark-ready")} busy={statusBusy} label="Mark READY" busyLabel="…" />
                <SubmitButton onClick={() => transition("mark-draft")} busy={statusBusy} label="Mark DRAFT" busyLabel="…" />
                <SubmitButton onClick={() => transition("archive")} busy={statusBusy} label="Archive" busyLabel="…" />
              </div>
              <ErrorText>{statusError}</ErrorText>
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

// --- 2. Discover trigger + Stage-1 candidate list -------------------------------------

function DiscoverSection({
  getToken,
  runId,
  onRunStarted,
  onReload,
  report,
  reportBusy,
  reportError,
}: {
  getToken: () => Promise<string | null>;
  runId: string | null;
  onRunStarted: (runId: string) => void;
  onReload: () => void;
  report: PiReport | null;
  reportBusy: boolean;
  reportError: string | null;
}) {
  const [nicheBriefId, setNicheBriefId] = useState("");
  const [depth, setDepth] = useState<"SHALLOW" | "COMPLETE">("SHALLOW");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PiRunResult | null>(null);

  const discover = async () => {
    if (!nicheBriefId.trim()) {
      setError("Enter a READY niche brief id first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<PiRunResult>("/api/v1/pi/discover", await getToken(), {
        method: "POST",
        body: JSON.stringify({ niche_brief_id: nicheBriefId.trim(), depth }),
      });
      setResult(res);
      onRunStarted(res.runId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not run discovery — check the brief is READY and try again");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Discover Candidate Opportunities">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Niche brief id (must be READY)">
            <TextInput value={nicheBriefId} onChange={setNicheBriefId} placeholder="UUID" />
          </Field>
          <Field label="Depth">
            <SelectInput
              value={depth}
              onChange={(v) => setDepth(v as "SHALLOW" | "COMPLETE")}
              options={[
                { value: "SHALLOW", label: "SHALLOW" },
                { value: "COMPLETE", label: "COMPLETE" },
              ]}
            />
          </Field>
        </div>
        <div>
          <SubmitButton onClick={discover} busy={busy} label="Run discovery" busyLabel="Discovering…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
            Run <code>{result.runId}</code> — status {result.status} · {result.candidateIds.length} candidate(s) found
            {result.partialReason && <div style={{ color: "var(--negative)" }}>Partial: {result.partialReason}</div>}
            {result.failedReason && <div style={{ color: "var(--negative)" }}>Failed: {result.failedReason}</div>}
          </div>
        )}

        {runId && (
          <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[13px] font-semibold" style={{ color: "var(--text-3)" }}>
                Candidate opportunities — run <code>{runId}</code>
              </div>
              <SubmitButton onClick={onReload} busy={reportBusy} label="Reload report" busyLabel="Loading…" />
            </div>
            <ErrorText>{reportError}</ErrorText>
            {report && report.candidates.length === 0 && (
              <div className="text-[12.5px]" style={{ color: "var(--text-6)" }}>
                No candidates found for this run yet.
              </div>
            )}
            {report && (
              <div className="flex flex-col gap-3">
                {report.candidates.map((entry) => (
                  <CandidateCard key={entry.candidate.id} entry={entry} />
                ))}
                {report.unavailable.length > 0 && (
                  <div className="rounded-lg p-3 text-[12px]" style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}>
                    <div className="mb-1 font-semibold" style={{ color: "var(--text-4)" }}>
                      Not available in this report
                    </div>
                    {report.unavailable.map((u, i) => (
                      <div key={i} style={{ color: "var(--text-6)" }}>
                        {u.field}: {u.reason}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Section>
  );
}

function CandidateCard({ entry }: { entry: PiReportCandidateEntry }) {
  const [expanded, setExpanded] = useState(false);
  const c = entry.candidate;
  return (
    <div className="rounded-lg p-3 text-[12.5px]" style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}>
      <div className="flex gap-3">
        {c.image_url && (
          <div className="flex-shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={c.image_url} alt={c.candidate_title} className="h-16 w-16 rounded object-cover" />
            <div className="mt-1 text-[10.5px]" style={{ color: "var(--text-7)" }}>
              image from {imageDomain(c.image_source_url)}
            </div>
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <strong style={{ color: "var(--text-2)" }}>{c.candidate_title}</strong>
            <ConfidenceBadge status="available" label="Candidate opportunity" reason="signal-based estimate — not a claim of verified marketplace sales rank or current demand spike" />
          </div>
          <div className="mt-1" style={{ color: "var(--text-5)" }}>
            Proxy score:{" "}
            {c.proxy_state === "COMPUTED" ? (
              <span>{c.proxy_score}/100</span>
            ) : (
              <ConfidenceBadge status="unavailable" label="UNAVAILABLE" reason="no engagement or source-diversity signal available" />
            )}
            {" · "}
            {c.source_diversity} independent source(s)
          </div>

          <WebPriceSignalRow signal={c.web_price_signal} />

          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 text-[11.5px] font-semibold"
            style={{ color: "var(--accent)" }}
          >
            {expanded ? "Hide score explanation" : "Show score explanation"}
          </button>
          {expanded && (
            <div className="mt-1.5 flex flex-col gap-1">
              <div style={{ color: "var(--text-6)" }}>{c.score_explanation.summary}</div>
              {c.score_explanation.signals.map((s, i) => (
                <div key={i} className="flex gap-2" style={{ color: "var(--text-6)" }}>
                  <ConfidenceBadge
                    status={s.status === "AVAILABLE" ? "available" : "unavailable"}
                    label={`${s.signal}: ${s.points}/${s.max_points}`}
                    reason={s.reason}
                  />
                </div>
              ))}
            </div>
          )}

          {entry.final_score_state === "COMPUTED" && (
            <div className="mt-1.5" style={{ color: "var(--text-5)" }}>
              Final shortlist score: {entry.final_score}/100 —{" "}
              {entry.final_score_explanation?.summary ?? ""}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function WebPriceSignalRow({ signal }: { signal: PiCandidate["web_price_signal"] }) {
  if (!signal || signal.status === "UNAVAILABLE") {
    return (
      <div className="mt-1">
        <ConfidenceBadge status="unavailable" label="Web price signal: UNAVAILABLE" reason={signal?.reason ?? "no price mention found"} />
      </div>
    );
  }
  return (
    <div className="mt-1">
      <ConfidenceBadge
        status="available"
        label={`Other sources mention prices around ₹${(signal.average_paise / 100).toFixed(2)} (₹${(signal.range_low_paise / 100).toFixed(2)}–₹${(signal.range_high_paise / 100).toFixed(2)}, ${signal.sample_count} mention(s))`}
        reason={signal.disclaimer}
      />
    </div>
  );
}

// --- 3. Shortlist / viewer & web commentary + supplier view ---------------------------

function ShortlistSupplierSection({
  getToken,
  runId,
  report,
  onReload,
}: {
  getToken: () => Promise<string | null>;
  runId: string | null;
  report: PiReport | null;
  onReload: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PiSupplierLookupResponse | null>(null);

  const toggle = (id: string) =>
    setSelected((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : ids.length < 5 ? [...ids, id] : ids));

  const runSupplierLookup = async () => {
    if (!runId || selected.length === 0) {
      setError("Load a discovery run and select at least one candidate first (up to 5).");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<PiSupplierLookupResponse>("/api/v1/pi/supplier-lookup", await getToken(), {
        method: "POST",
        body: JSON.stringify({ run_id: runId, candidate_ids: selected }),
      });
      setResult(res);
      onReload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not run supplier lookup");
    } finally {
      setBusy(false);
    }
  };

  if (!report) {
    return (
      <Section title="Shortlist Commentary + Supplier Leads">
        <div className="text-[12.5px]" style={{ color: "var(--text-6)" }}>
          Run discovery above first, then select candidates here to look up suppliers and view
          viewer/web commentary.
        </div>
      </Section>
    );
  }

  return (
    <Section title="Shortlist Commentary + Supplier Leads">
      <div className="flex flex-col gap-3">
        <div className="text-[12.5px]" style={{ color: "var(--text-6)" }}>
          Select up to 5 candidates to look up suppliers for.
        </div>
        <div className="flex flex-col gap-2">
          {report.candidates.map((entry) => (
            <div key={entry.candidate.id} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
              <label className="flex items-center gap-2 text-[13px]" style={{ color: "var(--text-3)" }}>
                <input
                  type="checkbox"
                  checked={selected.includes(entry.candidate.id)}
                  onChange={() => toggle(entry.candidate.id)}
                />
                <strong>{entry.candidate.candidate_title}</strong>
              </label>

              <div className="mt-2 flex flex-col gap-1.5">
                {entry.review_insights.length === 0 ? (
                  <div className="text-[12px]" style={{ color: "var(--text-6)" }}>
                    No viewer or web commentary gathered for this candidate yet.
                  </div>
                ) : (
                  entry.review_insights.map((ri) => (
                    <div key={ri.id} className="text-[12px]" style={{ color: "var(--text-5)" }}>
                      <ConfidenceBadge
                        status="available"
                        label={ri.insight_source_type === "YOUTUBE_COMMENTARY" ? "Viewer commentary (YouTube)" : "Web editorial commentary"}
                        reason={
                          ri.degraded_reason ??
                          `${ri.reviews_considered ?? 0} comment/snippet source(s) considered — never a marketplace buyer rating record`
                        }
                      />
                    </div>
                  ))
                )}
              </div>

              <div className="mt-2 flex flex-col gap-1.5">
                {entry.supplier_leads.length === 0 ? (
                  <div className="text-[12px]" style={{ color: "var(--text-6)" }}>
                    No supplier leads found yet — run supplier lookup below.
                  </div>
                ) : (
                  entry.supplier_leads.map((lead) => (
                    <div key={lead.id} className="text-[12px]" style={{ color: "var(--text-3)" }}>
                      <strong>{lead.supplier_name}</strong> · {lead.source}
                      {lead.source_url && (
                        <>
                          {" · "}
                          <a href={lead.source_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
                            link
                          </a>
                        </>
                      )}
                      {" · "}
                      {lead.contact?.moq ? (
                        <span>
                          MOQ: {lead.contact.moq.quantity} units @ {rupees(lead.contact.moq.unit_price_paise)}
                        </span>
                      ) : (
                        <span style={{ color: "var(--text-6)" }}>MOQ not published — contact supplier to confirm</span>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
        <div>
          <SubmitButton onClick={runSupplierLookup} busy={busy} label="Run supplier lookup" busyLabel="Looking up…" />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
            {result.results.map((r) => (
              <div key={r.candidateId}>
                Candidate <code>{r.candidateId.slice(0, 8)}</code>: {r.leadIds.length} lead(s) found
                {r.degradedReason && <span style={{ color: "var(--negative)" }}> — {r.degradedReason}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  );
}

// --- 4. Final recommendation ------------------------------------------------------------

function FinalRecommendationSection() {
  return (
    <Section title="Final Recommendation">
      <ConfidenceBadge
        status="unavailable"
        label="Not yet available — requires CFO batch-size integration (Phase 2 agent wiring, not yet done)"
        reason="PI's Phase 2 currently exposes only plain HTTP routes (discover, supplier lookup, report). The CEO→CFO batch-size handoff that assembles a final per-candidate recommendation (target price margin, recommended quantity, consider-addressing list) has not been wired yet — this section will render real data once that agent wiring is separately approved and built, never a faked or partial version in the meantime."
      />
    </Section>
  );
}
