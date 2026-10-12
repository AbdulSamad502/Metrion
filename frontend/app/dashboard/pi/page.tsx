"use client";

import Link from "next/link";
import { PAGE_COPY } from "@/lib/navigation";
import { useAuth } from "@clerk/nextjs";
import { useEffect, useState, createContext, useContext, useId } from "react";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { Icon } from "@/components/ui/Icon";
import { ConfidenceBadge } from "@/components/ui/ConfidenceBadge";
import { PipelineStepper, type FlowStep } from "@/components/ci/EvidenceTrail";
import { Section } from "@/components/ui/Section";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { useHashTab } from "@/lib/useHashTab";
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
import { friendlyApiError } from "@/lib/apiErrors";
import { rupeesToPaise } from "@/lib/costInput";

/** PI test harness — a real, functional, deliberately undecorated dashboard for clicking
 * through PI's direct-execution routes (`backend/src/backend/api/v1/pi.py`) against the
 * signed-in tenant's own data. Mirrors `dashboard/cfo/page.tsx` and `dashboard/ceo-hub/
 * page.tsx`'s exact conventions (Section, per-form busy/error/result state, a fresh Clerk
 * token per call, money entered/rendered in rupees converted to/from paise at the edge
 * only). No mock data anywhere — every section calls a real backend route and renders
 * exactly what comes back, including genuine UNAVAILABLE/error/empty states.
 *
 * This page does not produce a recommendation: the "final recommendation" section says so and links to the new-product decision in Ask Metrion, which checks a
 * product against the seller's own saved costs. Nothing here is a faked or partial version of that. */
const PI_TABS = [
  { id: "discover", label: "Niche & discovery" },
  { id: "shortlist", label: "Shortlist & suppliers" },
  { id: "recommendation", label: "Recommendation" },
] as const;

export default function PiPage() {
  return (
    <DashboardShell {...PAGE_COPY["products"]}>
      <PiWorkspace />
    </DashboardShell>
  );
}

const PI_STEPS: FlowStep[] = [
  { name: "Opportunity", detail: "Describe a niche, budget and price band." },
  { name: "Candidates", detail: "Discovery proposes products from independent signals." },
  { name: "Evidence", detail: "Each score shows which signals it rests on — and which are missing." },
  { name: "Feasibility", detail: "An estimate against your costs. Never confirmed profit." },
  { name: "Recommendation", detail: "Shortlist and compare suppliers, then decide." },
];

function PiWorkspace() {
  const { getToken } = useAuth();
  const [tab, setTab] = useHashTab(PI_TABS.map((t) => t.id), "discover");

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
      setReportError(friendlyApiError(e, "Could not load the PI report"));
    } finally {
      setReportBusy(false);
    }
  };

  useEffect(() => {
    // "View the full research report" in the CEO Hub links here with ?run=<research run id>: open exactly that run
    const id = new URLSearchParams(window.location.search).get("run");
    if (id && /^[0-9a-f-]{36}$/i.test(id)) {
      const open = async () => {
        setRunId(id);
        await reloadReport(id);
      };
      void open();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mt-content flex flex-col gap-7">
      <PipelineStepper steps={PI_STEPS} label="Product discovery workflow" />
      <Tabs tabs={[...PI_TABS]} active={tab} onChange={setTab} label="Product Intelligence workspace" idPrefix="pi" />

      <TabPanel id="discover" active={tab} idPrefix="pi">
        <div className="mt-stack">
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
        </div>
      </TabPanel>
      <TabPanel id="shortlist" active={tab} idPrefix="pi">
        <ShortlistSupplierSection getToken={getToken} runId={runId} report={report} onReload={() => runId && reloadReport(runId)} />
      </TabPanel>
      <TabPanel id="recommendation" active={tab} idPrefix="pi">
        <FinalRecommendationSection />
      </TabPanel>
    </div>
  );
}

// --- Shared primitives (same inline CSS-variable convention ceo-hub/cfo pages use) ----

const FieldIdContext = createContext<string | undefined>(undefined);

/** The label is tied to its control (clicking it focuses the control, and assistive technology reads it as the control's name). */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block t-body-sm" style={{ color: "var(--text-6)" }}>
        {label}
      </label>
      <FieldIdContext.Provider value={id}>{children}</FieldIdContext.Provider>
    </div>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  ariaLabel,
}: {
  ariaLabel?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  const fieldId = useContext(FieldIdContext);
  return (
    <input
      id={ariaLabel ? undefined : fieldId}
      aria-label={ariaLabel}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
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
      id={useContext(FieldIdContext)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="mt-input w-full rounded-lg px-3 py-2 t-body"
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
  primary = false,
}: {
  onClick: () => void;
  busy: boolean;
  label: string;
  busyLabel: string;
  /** The one green action of a view; every other submit is a neutral secondary button. */
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`mt-btn mt-focus w-fit rounded-lg px-4 py-2 t-body font-bold disabled:cursor-not-allowed ${primary ? "" : "mt-btn-secondary"}`}
      style={primary ? { background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 } : { opacity: busy ? 0.6 : 1 }}
    >
      {busy ? busyLabel : label}
    </button>
  );
}

function ErrorText({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div role="alert" className="t-body-sm" style={{ color: "var(--negative)" }}>
      {children}
    </div>
  );
}

function rupees(paise: number | null): string {
  return paise === null ? "—" : `₹${(paise / 100).toFixed(2)}`;
}

/** Rupees typed by the seller -> integer paise (the shared exact parser; "₹50,000" is fine). An unreadable amount is `null`, never NaN, which JSON would turn into a
 * silent `null` and drop the figure from the brief. */
function toPaise(rupeesStr: string): number | null {
  return rupeesToPaise(rupeesStr.replace(/₹/g, ""));
}

/** The §6.1 rule-2 fields a DRAFT still lacks before it can be marked READY (same rule the backend enforces). */
function missingForReady(b: PiNicheBrief): string[] {
  const out: string[] = [];
  if (!b.category_text) out.push("a category");
  if (b.budget_paise === null || b.budget_paise === undefined) out.push("a budget");
  if (!b.marketplaces || b.marketplaces.length === 0) out.push("at least one marketplace");
  return out;
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
  const [excludeBrands, setExcludeBrands] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createdBriefId, setCreatedBriefId] = useState<string | null>(null);

  const toggleMarketplace = (m: string) =>
    setMarketplaces((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m]));

  const createDraft = async () => {
    setCreateError(null);
    setCreatedBriefId(null);
    const money = { budget, "target minimum": targetMin, "target maximum": targetMax };
    const bad = Object.entries(money).find(([, v]) => v.trim() && toPaise(v) === null);
    if (bad) {
      setCreateError(`The ${bad[0]} must be an amount in rupees, like 50000 or 499.50. Nothing was saved.`);
      return;
    }
    setCreateBusy(true);
    try {
      const res = await apiFetch<{ nicheBriefId: string }>("/api/v1/pi/niche-briefs", await getToken(), {
        method: "POST",
        body: JSON.stringify({
          category_text: categoryText.trim() || null,
          budget_paise: budget.trim() ? toPaise(budget) : null,
          target_price_min_paise: targetMin.trim() ? toPaise(targetMin) : null,
          target_price_max_paise: targetMax.trim() ? toPaise(targetMax) : null,
          marketplaces: marketplaces.length > 0 ? marketplaces : null,
          constraints: excludeBrands.trim()
            ? { exclude_brands: excludeBrands.split(",").map((b) => b.trim()).filter(Boolean) }
            : null,
        }),
      });
      setCreatedBriefId(res.nicheBriefId);
    } catch (e) {
      setCreateError(friendlyApiError(e, "Could not create the niche brief draft"));
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
        setLookupError(friendlyApiError(e, "Could not load the niche brief"));
      }
    } finally {
      setLookupBusy(false);
    }
  };

  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusDone, setStatusDone] = useState<string | null>(null);

  const transition = async (action: "mark-ready" | "mark-draft" | "archive") => {
    if (!lookupBrief) return;
    setStatusBusy(true);
    setStatusError(null);
    setStatusDone(null);
    try {
      const res = await apiFetch<{ status: string }>(`/api/v1/pi/niche-briefs/${lookupBrief.id}/${action}`, await getToken(), { method: "POST" });
      await loadBrief();
      setStatusDone(`Status is now ${res.status}.`);
    } catch (e) {
      setStatusError(friendlyApiError(e, `Could not ${action.replace("-", " ")} this brief`));
    } finally {
      setStatusBusy(false);
    }
  };

  // Completing a DRAFT that lacks a field the READY rule needs: the existing PUT keeps every field that is not sent.
  const [fixCategory, setFixCategory] = useState("");
  const [fixBudget, setFixBudget] = useState("");
  const [fixMarketplaces, setFixMarketplaces] = useState<string[]>([]);
  const completeDraft = async () => {
    if (!lookupBrief) return;
    setStatusError(null);
    setStatusDone(null);
    if (fixBudget.trim() && toPaise(fixBudget) === null) {
      setStatusError("The budget must be an amount in rupees, like 50000 or 499.50. Nothing was saved.");
      return;
    }
    setStatusBusy(true);
    try {
      await apiFetch(`/api/v1/pi/niche-briefs/${lookupBrief.id}`, await getToken(), {
        method: "PUT",
        body: JSON.stringify({
          category_text: fixCategory.trim() || null,
          budget_paise: fixBudget.trim() ? toPaise(fixBudget) : null,
          marketplaces: fixMarketplaces.length > 0 ? fixMarketplaces : null,
        }),
      });
      await loadBrief();
      setFixCategory("");
      setFixBudget("");
      setFixMarketplaces([]);
      setStatusDone("Saved. Check what is still needed below, then mark it READY.");
    } catch (e) {
      setStatusError(friendlyApiError(e, "Could not save this brief"));
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <Section title="Niche Brief Intake">
      <div className="flex flex-col gap-6">
        <div>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>
            Create a draft
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <Field label="Category / product idea">
              <TextInput value={categoryText} onChange={setCategoryText} placeholder="e.g. kitchen storage jars" />
            </Field>
            <Field label="Budget (₹)">
              <TextInput value={budget} onChange={setBudget} placeholder="e.g. 50000" />
            </Field>
            <Field label="Target price range (₹)">
              <div className="flex gap-2">
                <TextInput value={targetMin} onChange={setTargetMin} placeholder="min" ariaLabel="Target minimum" />
                <TextInput value={targetMax} onChange={setTargetMax} placeholder="max" ariaLabel="Target maximum" />
              </div>
            </Field>
          </div>
          <div className="mt-3">
            <div className="mb-1 t-body-sm" style={{ color: "var(--text-6)" }}>
              Marketplaces
            </div>
            <div className="flex gap-3">
              {MARKETPLACE_OPTIONS.map((m) => (
                <label key={m} className="flex min-h-6 items-center gap-1.5 t-body" style={{ color: "var(--text-3)" }}>
                  <input type="checkbox" checked={marketplaces.includes(m)} onChange={() => toggleMarketplace(m)} />
                  {m}
                </label>
              ))}
            </div>
          </div>
          <div className="mt-3">
            <Field label="Exclude brands (optional)">
              <TextInput
                value={excludeBrands}
                onChange={setExcludeBrands}
                placeholder="e.g. Nike, Puma, Adidas — comma-separated, already-dominant brands to skip"
              />
            </Field>
            <div className="mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>
              Candidates matching these brand names are filtered out before discovery results are shown — a
              plain, seller-specified exclusion list, never an automated &quot;too famous&quot; judgement.
            </div>
          </div>
          <div className="mt-3">
            <SubmitButton onClick={createDraft} busy={createBusy} label="Create draft" busyLabel="Creating…" />
          </div>
          <ErrorText>{createError}</ErrorText>
          {createdBriefId && (
            <div className="mt-1 t-body-sm" style={{ color: "var(--accent)" }}>
              Created — niche brief <code>{createdBriefId}</code>. Use it below to mark it READY, then in the
              Discover section.
            </div>
          )}
        </div>

        <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
          <div className="mb-2 t-body font-semibold" style={{ color: "var(--text-3)" }}>
            Look up a niche brief
          </div>
          <div className="flex gap-2">
            <TextInput value={lookupBriefId} onChange={setLookupBriefId} placeholder="niche brief id (UUID)" ariaLabel="Niche brief id to look up" />
            <SubmitButton onClick={loadBrief} busy={lookupBusy} label="Load" busyLabel="Loading…" />
          </div>
          <ErrorText>{lookupError}</ErrorText>
          {lookupNotFound && <div className="mt-1 t-body-sm" style={{ color: "var(--text-6)" }}>Not found for this tenant.</div>}
          {lookupBrief && (
            <div className="mt-3 rounded-lg p-3 t-body-sm" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <div style={{ color: "var(--text-2)" }}>
                <strong>{lookupBrief.category_text ?? "(no category set)"}</strong> — status {lookupBrief.status}
              </div>
              <div style={{ color: "var(--text-5)" }}>
                Budget: {rupees(lookupBrief.budget_paise)} · Target: {rupees(lookupBrief.target_price_min_paise)}–
                {rupees(lookupBrief.target_price_max_paise)} · Marketplaces:{" "}
                {lookupBrief.marketplaces?.join(", ") ?? "none set"}
              </div>
              {Array.isArray(lookupBrief.constraints?.exclude_brands) && (lookupBrief.constraints!.exclude_brands as string[]).length > 0 && (
                <div style={{ color: "var(--text-6)" }}>
                  Excluding brands: {(lookupBrief.constraints!.exclude_brands as string[]).join(", ")}
                </div>
              )}
              {lookupBrief.status === "DRAFT" && missingForReady(lookupBrief).length > 0 && (
                <div className="mt-2 flex flex-col gap-2" data-testid="brief-needs">
                  <div style={{ color: "var(--text-3)" }}>
                    Before this can be marked READY it needs {missingForReady(lookupBrief).join(", ")}.
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {!lookupBrief.category_text && (
                      <Field label="Category / product idea">
                        <TextInput value={fixCategory} onChange={setFixCategory} placeholder="e.g. kitchen storage jars" />
                      </Field>
                    )}
                    {lookupBrief.budget_paise === null && (
                      <Field label="Budget (₹)">
                        <TextInput value={fixBudget} onChange={setFixBudget} placeholder="e.g. 50000" />
                      </Field>
                    )}
                  </div>
                  {(!lookupBrief.marketplaces || lookupBrief.marketplaces.length === 0) && (
                    <div className="flex gap-3">
                      {MARKETPLACE_OPTIONS.map((m) => (
                        <label key={m} className="flex min-h-6 items-center gap-1.5 t-body" style={{ color: "var(--text-3)" }}>
                          <input
                            type="checkbox"
                            checked={fixMarketplaces.includes(m)}
                            onChange={() => setFixMarketplaces((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m]))}
                          />
                          {m}
                        </label>
                      ))}
                    </div>
                  )}
                  <SubmitButton onClick={completeDraft} busy={statusBusy} label="Save missing details" busyLabel="Saving…" />
                </div>
              )}
              <div className="mt-2 flex gap-2">
                <SubmitButton onClick={() => transition("mark-ready")} busy={statusBusy} label="Mark READY" busyLabel="…" />
                <SubmitButton onClick={() => transition("mark-draft")} busy={statusBusy} label="Mark DRAFT" busyLabel="…" />
                <SubmitButton onClick={() => transition("archive")} busy={statusBusy} label="Archive" busyLabel="…" />
              </div>
              <ErrorText>{statusError}</ErrorText>
              {statusDone && !statusError && (
                <div role="status" className="t-body-sm" style={{ color: "var(--accent)" }}>{statusDone}</div>
              )}
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
      setError(friendlyApiError(e, "Could not run discovery — check the brief is READY and try again"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Discover Candidate Opportunities">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
          <SubmitButton onClick={discover} busy={busy} label="Run discovery" busyLabel="Discovering…" primary />
        </div>
        <ErrorText>{error}</ErrorText>
        {result && (
          <div className="t-body-sm" style={{ color: "var(--text-3)" }}>
            Run <code>{result.runId}</code> — status {result.status} · {result.candidateIds.length} candidate(s) found
            {result.partialReason && <div style={{ color: "var(--negative)" }}>Partial: {result.partialReason}</div>}
            {result.failedReason && <div style={{ color: "var(--negative)" }}>Failed: {result.failedReason}</div>}
          </div>
        )}

        {runId && (
          <div style={{ borderTop: "1px solid var(--border-subtle)", paddingTop: 16 }}>
            <div className="mb-2 flex items-center justify-between">
              <div className="t-body font-semibold" style={{ color: "var(--text-3)" }}>
                Candidate opportunities — run <code>{runId}</code>
              </div>
              <SubmitButton onClick={onReload} busy={reportBusy} label="Reload report" busyLabel="Loading…" />
            </div>
            <ErrorText>{reportError}</ErrorText>
            {report && report.candidates.length === 0 && (
              <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
                No candidates found for this run yet.
              </div>
            )}
            {report && (
              <div className="flex flex-col gap-3">
                {report.candidates.map((entry) => (
                  <CandidateCard key={entry.candidate.id} entry={entry} />
                ))}
                {report.unavailable.length > 0 && (
                  <div className="rounded-lg p-3 t-meta" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
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

/** A candidate's image, exactly as discovery found it. The source is third-party (a hosting page's
 * image, or a YouTube thumbnail), so it can be dead, blocked or hotlink-protected: when it fails to
 * load the image is dropped and the cell falls back to the same neutral empty state as "no image" —
 * never a broken-image icon. `no-referrer` avoids hotlink protection that keys on our origin; the
 * fixed 64px box means a late or failed load never shifts the card's layout. */
function CandidateImage({ url, alt, sourceUrl }: { url: string | null; alt: string; sourceUrl: string | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!url || failedUrl === url) {
    // Neutral empty state: same 64px footprint as a real image so every card's text column lines up.
    // It claims nothing about the product — there is simply no (loadable) image for it.
    return (
      <div
        className="hidden h-16 w-16 flex-shrink-0 items-center justify-center rounded-lg sm:flex"
        style={{ background: "var(--fill-hover)", color: "var(--text-7)" }}
        title="No image available for this candidate"
        role="img"
        aria-label="No image available for this candidate"
      >
        <Icon name="products" size={20} />
      </div>
    );
  }
  return (
    <div className="row-span-2 flex-shrink-0 sm:row-span-1">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={alt}
        width={64}
        height={64}
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => setFailedUrl(url)}
        className="h-16 w-16 rounded-lg object-cover"
        style={{ background: "var(--fill-hover)" }}
      />
      <div className="mt-1 max-w-16 truncate t-micro" style={{ color: "var(--text-6)" }} title={`image from ${imageDomain(sourceUrl)}`}>
        {imageDomain(sourceUrl)}
      </div>
    </div>
  );
}

function CandidateCard({ entry }: { entry: PiReportCandidateEntry }) {
  const [expanded, setExpanded] = useState(false);
  const c = entry.candidate;
  const computed = c.proxy_state === "COMPUTED";
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-3 py-5 t-body sm:grid-cols-[auto_minmax(0,1fr)_auto]" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
      <CandidateImage url={c.image_url} alt={c.candidate_title} sourceUrl={c.image_source_url} />

      {/* OPPORTUNITY — what it is, and how strong the signal is */}
      <div className="min-w-0">
        <div className="t-section font-semibold leading-snug" style={{ color: "var(--text-1)" }}>
          {c.candidate_title}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <ConfidenceBadge status="available" label="Candidate opportunity" reason="signal-based estimate — not a claim of verified marketplace sales rank or current demand spike" />
          <span style={{ color: "var(--text-5)" }}>{c.source_diversity} independent source(s)</span>
        </div>
      </div>

      <div className="col-span-2 flex items-baseline gap-2 sm:col-span-1 sm:flex-col sm:items-end sm:gap-0 sm:text-right">
        <div className="mt-eyebrow">Proxy score</div>
        {computed ? (
          <div className="mt-num t-metric font-bold leading-none" style={{ color: "var(--text-1)" }}>
            {c.proxy_score}
            <span className="t-body font-medium" style={{ color: "var(--text-5)" }}>
              /100
            </span>
          </div>
        ) : (
          <ConfidenceBadge status="unavailable" label="UNAVAILABLE" reason="no engagement or source-diversity signal available" />
        )}
      </div>

      {/* EVIDENCE → FEASIBILITY → RECOMMENDATION, in that order */}
      <div className="col-span-2 flex flex-col gap-3 sm:col-start-2 sm:col-span-2">
        <WebPriceSignalRow signal={c.web_price_signal} />
        <FeasibilityRow candidate={c} />

        {entry.final_score_state === "COMPUTED" && (
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 pl-3" style={{ borderLeft: "2px solid var(--glass-border-hover)" }}>
            <span className="mt-eyebrow">Shortlist score</span>
            <span className="mt-num t-headline font-bold" style={{ color: "var(--text-1)" }}>
              {entry.final_score}/100
            </span>
            <span style={{ color: "var(--text-4)" }}>{entry.final_score_explanation?.summary ?? ""}</span>
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="mt-btn mt-focus rounded-md t-body-sm font-semibold"
            style={{ color: "var(--text-3)" }}
          >
            {expanded ? "Hide how this score was built" : "How was this score built?"}
          </button>
          {expanded && (
            <div className="mt-fade-up mt-2 flex flex-col gap-1.5">
              <div style={{ color: "var(--text-4)" }}>{c.score_explanation.summary}</div>
              {c.score_explanation.signals.map((s, i) => (
                <div key={i} className="flex gap-2" style={{ color: "var(--text-5)" }}>
                  <ConfidenceBadge
                    status={s.status === "AVAILABLE" ? "available" : "unavailable"}
                    label={`${s.signal}: ${s.points}/${s.max_points}`}
                    reason={s.reason}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function FeasibilityRow({ candidate: c }: { candidate: PiCandidate }) {
  if (c.feasibility_status !== "COMPUTED") {
    return (
      <div className="mt-1">
        <ConfidenceBadge
          status="unavailable"
          label="Feasibility: UNAVAILABLE"
          reason={c.feasibility_unavailable_reason ?? "feasibility has not been computed for this candidate yet"}
        />
      </div>
    );
  }
  const isUnknownCogs = c.feasibility_cogs_basis === "UNKNOWN";
  return (
    <div className="mt-1">
      <ConfidenceBadge
        status="available"
        label={`Feasibility estimate: ${rupees(c.feasibility_low_paise)} – ${rupees(c.feasibility_high_paise)}${isUnknownCogs ? " (cost unknown)" : ""}`}
        reason={
          isUnknownCogs
            ? "No supplier quote yet — this range reflects your stated price band and marketplace fee spread ONLY. It is NOT a margin estimate; never treat it as confirmed profit."
            : (c.feasibility_assumptions ?? []).join(" ")
        }
      />
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
      setError(friendlyApiError(e, "Could not run supplier lookup"));
    } finally {
      setBusy(false);
    }
  };

  if (!report) {
    return (
      <Section title="Shortlist Commentary + Supplier Leads">
        <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
          Run discovery above first, then select candidates here to look up suppliers and view
          viewer/web commentary.
        </div>
      </Section>
    );
  }

  return (
    <Section title="Shortlist Commentary + Supplier Leads">
      <div className="flex flex-col gap-3">
        <div className="t-body-sm" style={{ color: "var(--text-6)" }}>
          Select up to 5 candidates to look up suppliers for.
        </div>
        <div className="flex flex-col gap-2">
          {report.candidates.map((entry) => (
            <div key={entry.candidate.id} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
              <label className="flex min-h-6 items-center gap-2 t-body" style={{ color: "var(--text-3)" }}>
                <input
                  type="checkbox"
                  checked={selected.includes(entry.candidate.id)}
                  onChange={() => toggle(entry.candidate.id)}
                />
                <strong>{entry.candidate.candidate_title}</strong>
              </label>

              <div className="mt-2 flex flex-col gap-1.5">
                {entry.review_insights.length === 0 ? (
                  <div className="t-meta" style={{ color: "var(--text-6)" }}>
                    No viewer or web commentary gathered for this candidate yet.
                  </div>
                ) : (
                  entry.review_insights.map((ri) => (
                    <div key={ri.id} className="t-meta" style={{ color: "var(--text-5)" }}>
                      <ConfidenceBadge
                        status="available"
                        label={ri.insight_source_type === "YOUTUBE_COMMENTARY" ? "Viewer commentary (YouTube)" : "Web editorial commentary"}
                        reason={
                          ri.degraded_reason ??
                          `${ri.reviews_considered ?? 0} comment/snippet source(s) considered — never a marketplace buyer rating record`
                        }
                      />
                      {ri.sentiment_split && (
                        <div className="mt-1 ml-1" style={{ color: "var(--text-6)" }}>
                          Sentiment: {Object.entries(ri.sentiment_split).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(" · ")}
                        </div>
                      )}
                      {ri.positive_themes && Object.keys(ri.positive_themes).length > 0 && (
                        <div className="mt-0.5 ml-1" style={{ color: "var(--positive)" }}>
                          Liked: {Object.entries(ri.positive_themes).map(([k, v]) => `${k} (${v})`).join(", ")}
                        </div>
                      )}
                      {ri.complaint_themes && Object.keys(ri.complaint_themes).length > 0 && (
                        <div className="mt-0.5 ml-1" style={{ color: "var(--negative)" }}>
                          Consider addressing: {Object.entries(ri.complaint_themes).map(([k, v]) => `${k} (${v})`).join(", ")}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              <div className="mt-2 flex flex-col gap-1.5">
                {entry.supplier_leads.length === 0 ? (
                  <div className="t-meta" style={{ color: "var(--text-6)" }}>
                    No supplier leads found yet — run supplier lookup below.
                  </div>
                ) : (
                  entry.supplier_leads.map((lead) => (
                    <div key={lead.id} className="t-meta" style={{ color: "var(--text-3)" }}>
                      <strong>{lead.supplier_name}</strong> · {lead.source}
                      {lead.locality && <> · {lead.locality}</>}
                      {lead.source_url && (
                        <>
                          {" · "}
                          <a href={lead.source_url} target="_blank" rel="noreferrer" style={{ color: "var(--text-3)", textDecoration: "underline" }}>
                            link
                          </a>
                        </>
                      )}
                      {lead.contact?.phone && <> · {lead.contact.phone}</>}
                      {lead.contact?.website && (
                        <>
                          {" · "}
                          <a href={lead.contact.website} target="_blank" rel="noreferrer" style={{ color: "var(--text-3)", textDecoration: "underline" }}>
                            website
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
          <div className="t-body-sm" style={{ color: "var(--text-3)" }}>
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
        label="Not produced on this page"
        reason="This page shows candidates, evidence and supplier leads; it does not recommend what to buy. To check a product against your own costs and budget, run the new-product decision in Ask Metrion. It uses your saved figures and says what is missing."
      />
      <div className="mt-3">
        <Link href="/dashboard/ceo-hub?form=new-product" className="mt-btn mt-btn-secondary mt-focus inline-flex items-center gap-1.5 rounded-xl px-3.5 py-2 t-body font-semibold">
          Check a product in Ask Metrion <Icon name="arrow" size={13} strokeWidth={1.9} />
        </Link>
      </div>
    </Section>
  );
}
