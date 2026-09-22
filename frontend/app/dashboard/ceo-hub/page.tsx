"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { useAppSession } from "@/lib/useAppSession";
import {
  ApiError,
  apiFetch,
  apiFetchForm,
  type AgentStatus,
  type Candidate,
  type ComparisonResult,
  type CompetitorUrl,
  type DigestPreview,
  type DiscoveryRunDetail,
  type DiscoveryRunStart,
  type MarketOverview,
  type ListingDiffResult,
  type MetricResult,
  type PriceEventItem,
  type PriceScenarioResult,
  type ResearchNowResult,
  type RunLinkage,
  type SellerProduct,
  type SnapshotHistoryItem,
} from "@/lib/api";

/** Step 4 — minimal, functional CEO Hub: Dashboard -> CEO Hub -> Dummy CEO -> CI -> result.
 * Deliberately undecorated per scope — a full visual pass happens once every agent is wired. */
export default function CeoHubPage() {
  const { session, error: sessionError, displayName, roleLabel } = useAppSession();
  const { getToken } = useAuth();

  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [urls, setUrls] = useState<CompetitorUrl[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const token = await getToken();
      const [a, u] = await Promise.all([
        apiFetch<AgentStatus[]>("/api/v1/ceo-hub/agents", token),
        apiFetch<CompetitorUrl[]>("/api/v1/ci/competitor-urls", token),
      ]);
      setAgents(a);
      setUrls(u);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Could not reach the backend");
    }
  };

  useEffect(() => {
    if (!session) return;
    (async () => {
      await reload();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (sessionError) {
    return <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--negative)" }}>{sessionError}</div>;
  }
  if (!session) {
    return <div className="flex h-screen w-full items-center justify-center" style={{ color: "var(--text-5)" }}>Loading…</div>;
  }

  return (
    <div className="flex" style={{ background: "var(--bg-base)" }}>
      <Sidebar userName={displayName} roleLabel={roleLabel} active="CEO Hub" />
      <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar title="CEO Hub" subtitle="Dashboard → CEO Hub → CEO → Agent → Result" />
        <div className="flex-1 overflow-y-auto px-8 py-7">
          {loadError && <div className="mb-4 text-sm" style={{ color: "var(--negative)" }}>{loadError}</div>}
          <AgentStatusSection agents={agents} />
          <div className="mt-6">
            <CompetitorResearchSection urls={urls} getToken={getToken} onChanged={reload} />
          </div>
          <div className="mt-6">
            <SellerProductSection getToken={getToken} />
          </div>
          <div className="mt-6">
            <DiscoverySection getToken={getToken} onAccepted={reload} />
          </div>
          <div className="mt-6">
            <MarketOverviewSection getToken={getToken} />
          </div>
          <div className="mt-6">
            <DigestSection getToken={getToken} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2.5 text-[16.5px] font-bold" style={{ color: "var(--text-2)" }}>{title}</div>
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}
      >
        {children}
      </div>
    </div>
  );
}

function AgentStatusSection({ agents }: { agents: AgentStatus[] | null }) {
  return (
    <Section title="Agent Status">
      {!agents ? (
        <div style={{ color: "var(--text-6)" }}>Loading…</div>
      ) : (
        <div className="flex flex-wrap gap-3">
          {agents.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px]"
              style={{ border: "1px solid var(--border-default)" }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: a.status === "CONNECTED" ? "var(--accent)" : "var(--text-7)" }}
              />
              <span style={{ color: "var(--text-2)" }}>{a.name}</span>
              <span style={{ color: a.status === "CONNECTED" ? "var(--accent)" : "var(--text-7)" }}>
                {a.status === "CONNECTED" ? "Connected" : "Not connected yet"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function CompetitorResearchSection({
  urls,
  getToken,
  onChanged,
}: {
  urls: CompetitorUrl[] | null;
  getToken: () => Promise<string | null>;
  onChanged: () => void;
}) {
  const [newUrl, setNewUrl] = useState("");
  const [newLinkedSku, setNewLinkedSku] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [selectedUrlId, setSelectedUrlId] = useState<string>("");
  // Bumped after every successful Research Now — CompetitorDetailSection's effect depends
  // on this too, so a completed run refreshes its snapshot/price-event/listing-diff data
  // automatically instead of requiring the manual "Refresh" click.
  const [detailRefreshTick, setDetailRefreshTick] = useState(0);
  const afterResearch = () => {
    setDetailRefreshTick((n) => n + 1);
    onChanged();
  };

  const addUrl = async () => {
    setAddError(null);
    try {
      const token = await getToken();
      await apiFetch("/api/v1/ci/competitor-urls", token, {
        method: "POST",
        body: JSON.stringify({ url: newUrl, linked_sku: newLinkedSku.trim() || null }),
      });
      setNewUrl("");
      setNewLinkedSku("");
      onChanged();
    } catch (e) {
      setAddError(e instanceof ApiError ? e.message : "Could not add competitor URL");
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <Section title="Tracked Competitors">
        <div className="flex flex-col gap-2">
          {urls === null ? (
            <div style={{ color: "var(--text-6)" }}>Loading…</div>
          ) : urls.length === 0 ? (
            <div style={{ color: "var(--text-6)" }}>No competitors tracked yet — add one below.</div>
          ) : (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr style={{ color: "var(--text-6)" }}>
                  <th className="pb-2 font-semibold">Marketplace</th>
                  <th className="pb-2 font-semibold">URL</th>
                  <th className="pb-2 font-semibold">Label</th>
                  <th className="pb-2 font-semibold">Linked SKU</th>
                  <th className="pb-2 font-semibold">Tags</th>
                </tr>
              </thead>
              <tbody>
                {urls.map((u) => (
                  <tr
                    key={u.id}
                    style={{ borderTop: "1px solid var(--border-subtle)", cursor: "pointer" }}
                    onClick={() => setSelectedUrlId(u.id)}
                  >
                    <td className="py-2" style={{ color: "var(--text-3)" }}>{u.marketplace}</td>
                    <td className="py-2 truncate" style={{ color: "var(--text-3)", maxWidth: 320 }}>{u.url}</td>
                    <td className="py-2" style={{ color: "var(--text-3)" }}>{u.label ?? "—"}</td>
                    <td className="py-2" style={{ color: "var(--text-3)" }}>{u.linkedSku ?? "—"}</td>
                    <td className="py-2" style={{ color: "var(--text-5)" }}>{u.tags.join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="mt-3 flex gap-2">
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://amazon.in/dp/... (reference only — never fetched)"
              className="flex-1 rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
            <input
              value={newLinkedSku}
              onChange={(e) => setNewLinkedSku(e.target.value)}
              placeholder="Link to SKU (optional — needed for Market Overview)"
              className="w-64 rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
            <button
              type="button"
              onClick={addUrl}
              className="rounded-lg px-4 py-2 text-[13px] font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Add
            </button>
          </div>
          <div className="text-[12px]" style={{ color: "var(--text-6)" }}>
            A competitor is only counted in Market Overview&apos;s price band if it&apos;s linked to a
            product SKU — either through Discover Competitors (automatic) or the &quot;Link to
            SKU&quot; box above (manual).
          </div>
          {addError && <div className="text-[12.5px]" style={{ color: "var(--negative)" }}>{addError}</div>}
        </div>
      </Section>

      <Section title="Research Now / Research Again">
        {urls && urls.length > 0 ? (
          <>
            <label className="mb-2 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Competitor</label>
            <select
              value={selectedUrlId}
              onChange={(e) => setSelectedUrlId(e.target.value)}
              className="mb-4 w-full rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            >
              <option value="">Select a competitor…</option>
              {urls.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.label ?? u.url}
                </option>
              ))}
            </select>
            {selectedUrlId && <ResearchForm competitorUrlId={selectedUrlId} getToken={getToken} onChanged={afterResearch} />}
          </>
        ) : (
          <div style={{ color: "var(--text-6)" }}>Add a competitor above to start researching it.</div>
        )}
      </Section>

      {selectedUrlId && (
        <CompetitorDetailSection
          key={selectedUrlId}
          url={urls?.find((u) => u.id === selectedUrlId) ?? null}
          getToken={getToken}
          onChanged={onChanged}
          refreshTick={detailRefreshTick}
        />
      )}
    </div>
  );
}

function CompetitorDetailSection({
  url,
  getToken,
  onChanged,
  refreshTick,
}: {
  url: CompetitorUrl | null;
  getToken: () => Promise<string | null>;
  onChanged: () => void;
  refreshTick: number;
}) {
  const [history, setHistory] = useState<SnapshotHistoryItem[] | null>(null);
  const [events, setEvents] = useState<PriceEventItem[] | null>(null);
  const [listingDiff, setListingDiff] = useState<ListingDiffResult | null>(null);
  // Lazy initializer, not an effect — the parent remounts this component (key={url.id})
  // whenever the selected competitor changes, so this only ever runs once per selection.
  const [tagsInput, setTagsInput] = useState(() => url?.tags.join(", ") ?? "");
  const [tagsSaving, setTagsSaving] = useState(false);
  const [tagsError, setTagsError] = useState<string | null>(null);
  const [tagsSaved, setTagsSaved] = useState(false);

  const loadDetail = async (urlId: string) => {
    const token = await getToken();
    const [h, e, d] = await Promise.all([
      apiFetch<SnapshotHistoryItem[]>(`/api/v1/ci/competitor-urls/${urlId}/snapshots`, token),
      apiFetch<PriceEventItem[]>(`/api/v1/ci/competitor-urls/${urlId}/price-events`, token),
      apiFetch<ListingDiffResult>(`/api/v1/ci/competitor-urls/${urlId}/listing-diff`, token),
    ]);
    setHistory(h);
    setEvents(e);
    setListingDiff(d);
  };

  useEffect(() => {
    if (!url) return;
    (async () => {
      await loadDetail(url.id);
    })();
    // refreshTick is intentionally a dependency: it bumps after every completed Research
    // Now for this competitor, so this panel updates itself instead of needing a manual
    // "Refresh" click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url?.id, refreshTick]);

  if (!url) return null;

  const saveTags = async () => {
    setTagsSaving(true);
    setTagsError(null);
    setTagsSaved(false);
    try {
      const token = await getToken();
      const tags = tagsInput.split(",").map((t) => t.trim()).filter(Boolean);
      await apiFetch(`/api/v1/ci/competitor-urls/${url.id}`, token, {
        method: "PATCH",
        body: JSON.stringify({ tags }),
      });
      setTagsSaved(true);
      onChanged();
    } catch (e) {
      // Previously swallowed silently — a failed save looked identical to a successful
      // one, since nothing rendered either way. Now surfaced directly.
      setTagsError(e instanceof ApiError ? e.message : "Could not save tags");
    } finally {
      setTagsSaving(false);
    }
  };

  const latestIsStale = history?.[0]?.isStale;

  return (
    <Section title={`Competitor Detail — ${url.label ?? url.url}`}>
      <div className="flex flex-col gap-5">
        <button
          type="button"
          onClick={() => loadDetail(url.id)}
          className="w-fit text-[12px] font-semibold"
          style={{ color: "var(--accent)" }}
        >
          Refresh
        </button>
        <div>
          <div className="mb-1 text-[12.5px] font-semibold" style={{ color: "var(--text-6)" }}>
            Tags
            {latestIsStale !== undefined && (
              <span className="ml-2" style={{ color: latestIsStale ? "var(--negative)" : "var(--accent)" }}>
                {latestIsStale ? "· Stale (>7 days)" : "· Fresh"}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <input
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="e.g. rival, budget-brand (comma-separated)"
              className="flex-1 rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
            <button
              type="button"
              onClick={saveTags}
              disabled={tagsSaving}
              className="rounded-lg px-3 py-2 text-[12.5px] font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: tagsSaving ? 0.6 : 1 }}
            >
              Save tags
            </button>
          </div>
          {tagsError && <div className="mt-1 text-[12px]" style={{ color: "var(--negative)" }}>{tagsError}</div>}
          {tagsSaved && !tagsError && (
            <div className="mt-1 text-[12px]" style={{ color: "var(--accent)" }}>Saved.</div>
          )}
        </div>

        <div>
          <div className="mb-1.5 text-[12.5px] font-semibold" style={{ color: "var(--text-6)" }}>
            Snapshot History
          </div>
          {history === null ? (
            <div style={{ color: "var(--text-6)" }}>Loading…</div>
          ) : history.length === 0 ? (
            <div style={{ color: "var(--text-6)" }}>No research submitted yet.</div>
          ) : (
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr style={{ color: "var(--text-6)" }}>
                  <th className="pb-1.5 font-semibold">Captured</th>
                  <th className="pb-1.5 font-semibold">Status</th>
                  <th className="pb-1.5 font-semibold">Price</th>
                  <th className="pb-1.5 font-semibold">Availability</th>
                  <th className="pb-1.5 font-semibold">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                    <td className="py-1.5" style={{ color: h.isStale ? "var(--negative)" : "var(--text-3)" }}>
                      {new Date(h.capturedAt).toLocaleString()}
                      {h.isStale && " (stale)"}
                    </td>
                    <td className="py-1.5" style={{ color: "var(--text-3)" }}>{h.captureStatus}</td>
                    <td className="py-1.5" style={{ color: "var(--text-3)" }}>
                      {h.listedPricePaise !== null ? `₹${(h.listedPricePaise / 100).toFixed(2)}` : "—"}
                    </td>
                    <td className="py-1.5" style={{ color: "var(--text-3)" }}>{h.availability ?? "—"}</td>
                    <td className="py-1.5" style={{ color: "var(--text-5)" }}>{h.confidence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <div className="mb-1.5 text-[12.5px] font-semibold" style={{ color: "var(--text-6)" }}>
            Price / Availability Change Events
          </div>
          {events === null ? (
            <div style={{ color: "var(--text-6)" }}>Loading…</div>
          ) : events.length === 0 ? (
            <div style={{ color: "var(--text-6)" }}>No changes detected yet.</div>
          ) : (
            <div className="flex flex-col gap-1.5">
              {events.map((ev) => (
                <div
                  key={ev.id}
                  className="rounded-lg px-3 py-2 text-[12.5px]"
                  style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}
                >
                  <span style={{ color: ev.direction === "DECREASE" ? "var(--accent)" : "var(--text-2)" }}>
                    {ev.direction} {ev.deltaPct}% (₹{(Math.abs(ev.deltaPaise) / 100).toFixed(2)})
                  </span>
                  {ev.availabilityChange && <span style={{ color: "var(--text-5)" }}> · {ev.availabilityChange}</span>}
                  {ev.thresholdBreached && <span style={{ color: "var(--negative)" }}> · alert-worthy</span>}
                  <span style={{ color: "var(--text-6)" }}> · {new Date(ev.createdAt).toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <div className="mb-1.5 text-[12.5px] font-semibold" style={{ color: "var(--text-6)" }}>
            Listing Change (title / description / bullets / category)
          </div>
          {listingDiff === null ? (
            <div style={{ color: "var(--text-6)" }}>Loading…</div>
          ) : !listingDiff.available ? (
            <div style={{ color: "var(--text-6)" }}>{listingDiff.reason}</div>
          ) : listingDiff.changedFields.length === 0 ? (
            <div style={{ color: "var(--text-6)" }}>No listing changes between the two most recent snapshots.</div>
          ) : (
            <ul className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
              {listingDiff.changedFields.map((c) => (
                <li key={c.fieldName}>
                  <strong>{c.fieldName}</strong>: {String(c.priorValue ?? "—")} → {String(c.currentValue ?? "—")}
                </li>
              ))}
            </ul>
          )}
        </div>

        <PricePositioningForm competitorUrlId={url.id} getToken={getToken} />
        <ComparisonView competitorUrlId={url.id} getToken={getToken} />
      </div>
    </Section>
  );
}

/** Checkpoint 6 — competitor-intelligence-agent.md §6.19's four-bucket comparison. Requires
 * a product id (the same identifier used by the Seller Product form above) since a
 * competitor_url has no implicit product linkage. */
function ComparisonView({ competitorUrlId, getToken }: { competitorUrlId: string; getToken: () => Promise<string | null> }) {
  const [productIdInput, setProductIdInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComparisonResult | null>(null);

  const load = async () => {
    const productId = productIdInput.trim();
    if (!productId) {
      setError("Enter the seller product's SKU / marketplace item id first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const data = await apiFetch<ComparisonResult>(
        `/api/v1/ci/competitor-urls/${competitorUrlId}/comparison?product_id=${encodeURIComponent(productId)}`,
        token,
      );
      setResult(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the comparison");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const bucket = (title: string, entries: { field: string; state: string; detail: string; caveat: string | null }[]) => (
    <div className="mb-3">
      <div className="mb-1 text-xs font-medium" style={{ color: "var(--text-2)" }}>{title}</div>
      <ul className="ml-4 list-disc text-xs" style={{ color: "var(--text-4)" }}>
        {entries.map((e, i) => (
          <li key={i}>
            {e.detail}
            {e.state === "UNKNOWN" && <span style={{ color: "var(--text-5)" }}> (UNKNOWN)</span>}
            {e.caveat && <span style={{ color: "var(--negative)" }}> — {e.caveat}</span>}
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--border-1)" }}>
      <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-1)" }}>Compare vs. your product</div>
      <div className="mb-3 flex gap-2">
        <input
          type="text"
          value={productIdInput}
          onChange={(e) => setProductIdInput(e.target.value)}
          placeholder="Your product's SKU / marketplace item id"
          className="rounded border px-2 py-1 text-sm"
          style={{ borderColor: "var(--border-1)" }}
        />
        <button
          type="button"
          disabled={loading}
          onClick={load}
          className="rounded border px-3 py-1 text-sm"
          style={{ borderColor: "var(--border-1)", color: "var(--text-2)" }}
        >
          {loading ? "Loading…" : "Compare"}
        </button>
      </div>
      {error && <div className="mb-2 text-sm" style={{ color: "var(--negative)" }}>{error}</div>}
      {result && !result.available && (
        <div className="text-sm" style={{ color: "var(--text-5)" }}>Not available yet — {result.reason}</div>
      )}
      {result && result.available && (
        <div>
          {bucket("Listing gaps", result.listingGaps)}
          {bucket("Your strengths", result.productStrengths)}
          {bucket("Cannot compare yet", result.productWeaknesses)}
          {bucket("Differentiation opportunities", result.differentiationOpportunities)}
        </div>
      )}
    </div>
  );
}

/** All price-positioning gaps share metricCode "PRICE_POSITIONING" (one row per reference
 * point) — the reference (AVERAGE/MIN/MAX) only appears in calculationBasis's
 * "PricePositioning vs AVERAGE (...)" text, so that's what distinguishes the rows here. */
function metricResultLabel(result: MetricResult): string {
  const basis = result.calculationBasis ?? "";
  if (basis.includes("vs AVERAGE")) return "vs. average";
  if (basis.includes("vs MIN")) return "vs. lowest";
  if (basis.includes("vs MAX")) return "vs. highest";
  return result.metricCode;
}

function MetricResultRow({ label, result }: { label: string; result: MetricResult }) {
  return (
    <div
      className="rounded-lg px-3 py-2 text-[12.5px]"
      style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}
    >
      <div style={{ color: "var(--text-2)" }}>
        <strong>{label}</strong>
        {": "}
        {result.isAvailable && result.valuePaise !== null ? (
          <span>
            {result.valuePaise >= 0 ? "+" : "-"}₹{(Math.abs(result.valuePaise) / 100).toFixed(2)}
          </span>
        ) : (
          <span style={{ color: "var(--text-6)" }}>
            UNAVAILABLE{result.unavailableReason ? ` — ${result.unavailableReason}` : ""}
          </span>
        )}
      </div>
      <div className="mt-0.5" style={{ color: "var(--text-7)" }}>
        confidence: {result.confidence} · ref: <code>{result.engineResultRef.slice(0, 8)}</code>
      </div>
    </div>
  );
}

/** §5.15's price-positioning/repricing scenario (Checkpoint 1) — calls the engine-backed
 * `/price-scenario` endpoint and renders whatever it returns unchanged, citing its
 * `engineResultRef`; no arithmetic on money happens here (per CLAUDE.md, that's the
 * engine's job). Every figure returned may be UNAVAILABLE (no usable competitor price
 * captured yet) — that's rendered as a plain message, never as an error or a blank. */
function PricePositioningForm({
  competitorUrlId,
  getToken,
}: {
  competitorUrlId: string;
  getToken: () => Promise<string | null>;
}) {
  const [sellerPriceRupees, setSellerPriceRupees] = useState("");
  const [stance, setStance] = useState<
    "" | "MATCH_LOWEST" | "BEAT_LOWEST_BY_PCT" | "BEAT_LOWEST_BY_PAISE" | "MATCH_AVERAGE" | "MATCH_HIGHEST"
  >("");
  const [stanceParamPct, setStanceParamPct] = useState("");
  const [stanceParamRupees, setStanceParamRupees] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PriceScenarioResult | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const check = async () => {
    if (!sellerPriceRupees.trim()) {
      setFormError("Enter your current price first.");
      return;
    }
    setBusy(true);
    setFormError(null);
    setResult(null);
    try {
      const body: Record<string, unknown> = {
        seller_price_paise: Math.round(parseFloat(sellerPriceRupees) * 100),
      };
      if (stance) {
        body.stance = stance;
        if (stance === "BEAT_LOWEST_BY_PCT" && stanceParamPct.trim()) {
          body.stance_param_pct = stanceParamPct.trim();
        }
        if (stance === "BEAT_LOWEST_BY_PAISE" && stanceParamRupees.trim()) {
          body.stance_param_paise = Math.round(parseFloat(stanceParamRupees) * 100);
        }
      }
      // A fresh token per call, not one reused across the flow — see ResearchForm's
      // submit() for why (Clerk session tokens are short-lived).
      const res = await apiFetch<PriceScenarioResult>(
        `/api/v1/ci/competitor-urls/${competitorUrlId}/price-scenario`,
        await getToken(),
        { method: "POST", body: JSON.stringify(body) },
      );
      setResult(res);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not check price position");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-1.5 text-[12.5px] font-semibold" style={{ color: "var(--text-6)" }}>
        Price Position / Repricing Scenario
      </div>
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Your price (₹)</label>
            <input
              value={sellerPriceRupees}
              onChange={(e) => setSellerPriceRupees(e.target.value)}
              placeholder="e.g. 999"
              className="w-full rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
          </div>
          <div>
            <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
              Stance (optional — leave blank for price position only)
            </label>
            <select
              value={stance}
              onChange={(e) => setStance(e.target.value as typeof stance)}
              className="w-full rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            >
              <option value="">— No stance —</option>
              <option value="MATCH_LOWEST">Match lowest</option>
              <option value="BEAT_LOWEST_BY_PCT">Beat lowest by %</option>
              <option value="BEAT_LOWEST_BY_PAISE">Beat lowest by ₹</option>
              <option value="MATCH_AVERAGE">Match average</option>
              <option value="MATCH_HIGHEST">Match highest</option>
            </select>
          </div>
        </div>
        {stance === "BEAT_LOWEST_BY_PCT" && (
          <div>
            <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Beat by (%)</label>
            <input
              value={stanceParamPct}
              onChange={(e) => setStanceParamPct(e.target.value)}
              placeholder="e.g. 2"
              className="w-full rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
          </div>
        )}
        {stance === "BEAT_LOWEST_BY_PAISE" && (
          <div>
            <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Beat by (₹)</label>
            <input
              value={stanceParamRupees}
              onChange={(e) => setStanceParamRupees(e.target.value)}
              placeholder="e.g. 10"
              className="w-full rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
          </div>
        )}
        <button
          type="button"
          onClick={check}
          disabled={busy}
          className="w-fit rounded-lg px-4 py-2 text-[13px] font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 }}
        >
          {busy ? "Checking…" : "Check price position"}
        </button>
        {formError && <div className="text-[12.5px]" style={{ color: "var(--negative)" }}>{formError}</div>}

        {result && (
          <div className="flex flex-col gap-1.5">
            {result.pricePositioning.every((r) => !r.isAvailable) ? (
              <div style={{ color: "var(--text-6)" }}>
                No usable competitor price yet — submit research with a price first.
              </div>
            ) : (
              result.pricePositioning.map((r) => (
                <MetricResultRow key={r.engineResultRef} label={metricResultLabel(r)} result={r} />
              ))
            )}
            {result.repricingScenario && (
              <MetricResultRow label="Repricing suggestion" result={result.repricingScenario} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ResearchForm({
  competitorUrlId,
  getToken,
  onChanged,
}: {
  competitorUrlId: string;
  getToken: () => Promise<string | null>;
  onChanged: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [priceRupees, setPriceRupees] = useState("");
  const [availability, setAvailability] = useState<"IN_STOCK" | "OUT_OF_STOCK" | "">("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResearchNowResult | null>(null);
  const [linkage, setLinkage] = useState<RunLinkage | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async () => {
    // Nothing to research at all — submitting anyway would silently produce a confusing
    // PENDING_MANUAL_ENTRY that looks like a broken feature rather than what it actually
    // is: no evidence was given. Stop here and say so plainly instead.
    if (!file && !priceRupees.trim() && !availability) {
      setFormError("Attach a screenshot, or fill in at least price or availability, before running research.");
      return;
    }
    setBusy(true);
    setFormError(null);
    setResult(null);
    setLinkage(null);
    try {
      // A fresh token per call, not one reused across the whole flow — Clerk session
      // tokens are short-lived (~60s), and a real vision-model research-now call can take
      // long enough (10-20s+ on constrained local hardware) that a token fetched before it
      // has expired by the time the final linkage fetch runs, surfacing as a confusing
      // "Not authenticated" alongside an otherwise-successful result.
      const imageRefs: string[] = [];
      if (file) {
        const form = new FormData();
        form.append("file", file);
        const uploaded = await apiFetchForm<{ imageRef: string }>("/api/v1/ci/evidence", await getToken(), form);
        imageRefs.push(uploaded.imageRef);
      }

      const manualFields: Record<string, unknown> = {};
      if (priceRupees.trim()) manualFields.listed_price_paise = Math.round(parseFloat(priceRupees) * 100);
      if (availability) manualFields.availability = availability;

      const res = await apiFetch<ResearchNowResult>("/api/v1/ceo-hub/research-now", await getToken(), {
        method: "POST",
        body: JSON.stringify({ competitor_url_id: competitorUrlId, image_refs: imageRefs, manual_fields: manualFields }),
      });
      setResult(res);

      const linked = await apiFetch<RunLinkage>(`/api/v1/ceo-hub/runs/${res.ceoAgentRunId}`, await getToken());
      setLinkage(linked);
      // Clear inputs on success — leaving the old filename/price displayed made it look
      // like they were still "attached" for the next Research Now click, when submitting
      // again would actually send nothing (this is what caused the confusing empty run).
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setPriceRupees("");
      setAvailability("");
      onChanged();
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Research run failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
          Screenshot (optional — attach one and fields below are extracted automatically; use
          the manual fields to fill in anything the model couldn&apos;t read, or if you have no
          screenshot at all)
        </label>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-[13px]"
          style={{ color: "var(--text-3)" }}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Price (₹)</label>
          <input
            value={priceRupees}
            onChange={(e) => setPriceRupees(e.target.value)}
            placeholder="e.g. 999"
            className="w-full rounded-lg px-3 py-2 text-[13px]"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
          />
        </div>
        <div>
          <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>Availability</label>
          <select
            value={availability}
            onChange={(e) => setAvailability(e.target.value as typeof availability)}
            className="w-full rounded-lg px-3 py-2 text-[13px]"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
          >
            <option value="">—</option>
            <option value="IN_STOCK">In stock</option>
            <option value="OUT_OF_STOCK">Out of stock</option>
          </select>
        </div>
      </div>
      <button
        type="button"
        onClick={submit}
        disabled={busy}
        className="w-fit rounded-lg px-4 py-2 text-[13px] font-bold"
        style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: busy ? 0.6 : 1 }}
      >
        {busy ? "Running…" : "Research Now"}
      </button>
      {formError && <div className="text-[12.5px]" style={{ color: "var(--negative)" }}>{formError}</div>}

      {result && (
        <div className="mt-2 rounded-lg p-3 text-[12.5px]" style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ color: "var(--text-2)" }}>
            <strong>Capture status:</strong> {result.ci.captureStatus ?? "—"} · <strong>Run status:</strong> {result.ci.status}
          </div>
          {result.ci.priceEventId && <div style={{ color: "var(--accent)" }}>Price change detected — event recorded.</div>}
          {linkage && (
            <div className="mt-2" style={{ color: "var(--text-5)" }}>
              CEO run <code>{linkage.parent.id.slice(0, 8)}</code> (parent: {linkage.parent.parentRunId ?? "none"}) → CI run(s):{" "}
              {linkage.children.map((c) => `${c.agentId}/${c.id.slice(0, 8)} (parent set ✓)`).join(", ") || "none yet"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** A small provenance badge for one `SellerProduct` field — distinguishes the three states
 * C31/§5.5.1 defines: already known from sales history (CANONICAL_DERIVED), entered by the
 * seller (SELLER_ENTERED), or UNKNOWN (absent from `fieldSource` entirely — never a default,
 * per C30/AC22). */
function FieldSourceBadge({ source }: { source: "CANONICAL_DERIVED" | "SELLER_ENTERED" | "UNKNOWN" }) {
  if (source === "CANONICAL_DERIVED") {
    return <span style={{ color: "var(--text-6)" }}>· from your sales data</span>;
  }
  if (source === "SELLER_ENTERED") {
    return <span style={{ color: "var(--accent)" }}>· you entered this</span>;
  }
  return <span style={{ color: "var(--negative)" }}>· missing — needs your input</span>;
}

type AttributeRow = { key: string; value: string };

/** Checkpoint 2 (C31/§5.5.1/§5.5.2) — the one-time-but-always-editable manual seller-product
 * profile form. Two sources exist server-side: CANONICAL_DERIVED (from `sales_line`, via
 * `derive_canonical`) and SELLER_ENTERED (this form, via `seller_product_profile`). The GET
 * response is already the merged view with a `fieldSource` per populated field; anything
 * absent from `fieldSource` is UNKNOWN by design (never a default, C30).
 *
 * `productId`: nothing in this frontend today surfaces a seller's catalog/product list to
 * pick from — `CompetitorUrl.linkedSku` is optional and per-competitor, not a seller-product
 * identifier space. Rather than fabricate a fake product picker that implies a catalog browse
 * exists, this asks the seller to type the identifier directly — their `sku` or
 * `marketplace_item_id`, matching exactly what the backend matches `product_id` against
 * (§5.5.2, `ci.py::get_seller_product`). A real product picker is future work once seller
 * catalog data is surfaced elsewhere in the app. */
function SellerProductSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [productIdInput, setProductIdInput] = useState("");
  const [loadedProductId, setLoadedProductId] = useState<string | null>(null);
  const [product, setProduct] = useState<SellerProduct | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [category, setCategory] = useState("");
  const [attributes, setAttributes] = useState<AttributeRow[]>([]);
  const [keywordsInput, setKeywordsInput] = useState("");
  const [priceRupees, setPriceRupees] = useState("");
  const [fulfillmentType, setFulfillmentType] = useState<"" | "SELLER_FULFILLED" | "MARKETPLACE_FULFILLED">("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const populateFormFrom = (p: SellerProduct | null) => {
    setCategory(p?.category ?? "");
    setAttributes(p?.attributes?.length ? p.attributes.map((a) => ({ ...a })) : []);
    setKeywordsInput(p?.keywords?.length ? p.keywords.join(", ") : "");
    setPriceRupees(p?.pricePaise !== null && p?.pricePaise !== undefined ? (p.pricePaise / 100).toFixed(2) : "");
    setFulfillmentType(
      p?.fulfillmentType === "SELLER_FULFILLED" || p?.fulfillmentType === "MARKETPLACE_FULFILLED"
        ? p.fulfillmentType
        : "",
    );
  };

  const loadProduct = async () => {
    const id = productIdInput.trim();
    if (!id) {
      setLoadError("Enter your product's SKU (or marketplace item id) first.");
      return;
    }
    setLoading(true);
    setLoadError(null);
    setSaved(false);
    setSaveError(null);
    setNotFound(false);
    try {
      const token = await getToken();
      const p = await apiFetch<SellerProduct>(`/api/v1/ci/seller-products/${encodeURIComponent(id)}`, token);
      setProduct(p);
      setLoadedProductId(id);
      populateFormFrom(p);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // No sales-history row and no profile yet for this id — not an error, just an
        // entirely UNKNOWN baseline the seller can now fill in from scratch (C30: absence
        // is UNKNOWN, never blocked).
        setProduct(null);
        setLoadedProductId(id);
        setNotFound(true);
        populateFormFrom(null);
      } else {
        setLoadError(e instanceof ApiError ? e.message : "Could not load the seller-product profile");
        setProduct(null);
        setLoadedProductId(null);
      }
    } finally {
      setLoading(false);
    }
  };

  const fieldSource = (field: string): "CANONICAL_DERIVED" | "SELLER_ENTERED" | "UNKNOWN" =>
    product?.fieldSource[field] ?? "UNKNOWN";

  const addAttributeRow = () => setAttributes((rows) => [...rows, { key: "", value: "" }]);
  const removeAttributeRow = (idx: number) => setAttributes((rows) => rows.filter((_, i) => i !== idx));
  const updateAttributeRow = (idx: number, patch: Partial<AttributeRow>) =>
    setAttributes((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const saveProfile = async () => {
    if (!loadedProductId) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const token = await getToken();
      const cleanAttributes = attributes
        .map((a) => ({ key: a.key.trim(), value: a.value.trim() }))
        .filter((a) => a.key && a.value);
      const keywords = keywordsInput.split(",").map((k) => k.trim()).filter(Boolean);
      const body: Record<string, unknown> = {
        category: category.trim() || null,
        attributes: cleanAttributes.length > 0 ? cleanAttributes : null,
        keywords: keywords.length > 0 ? keywords : null,
        price_paise: priceRupees.trim() ? Math.round(parseFloat(priceRupees) * 100) : null,
        fulfillment_type: fulfillmentType || null,
      };
      const updated = await apiFetch<SellerProduct>(
        `/api/v1/ci/seller-products/${encodeURIComponent(loadedProductId)}`,
        token,
        { method: "PUT", body: JSON.stringify(body) },
      );
      setProduct(updated);
      setNotFound(false);
      populateFormFrom(updated);
      setSaved(true);
    } catch (e) {
      // Show the real outcome either way — no silent success and no silent failure.
      setSaveError(e instanceof ApiError ? e.message : "Could not save the seller-product profile");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="Your Product Profile">
      <div className="flex flex-col gap-5">
        <div style={{ color: "var(--text-6)" }} className="text-[12.5px]">
          A one-time (but always-editable) profile for your own product. Fields already known
          from your sales history are filled in automatically; anything else is worth filling
          in yourself — relevance-scoring and competitor discovery depend on it.
        </div>

        <div>
          <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
            Product SKU (or marketplace item id)
          </label>
          <div className="flex gap-2">
            <input
              value={productIdInput}
              onChange={(e) => setProductIdInput(e.target.value)}
              placeholder="e.g. SKU-12345"
              className="flex-1 rounded-lg px-3 py-2 text-[13px]"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
            />
            <button
              type="button"
              onClick={loadProduct}
              disabled={loading}
              className="rounded-lg px-4 py-2 text-[13px] font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: loading ? 0.6 : 1 }}
            >
              {loading ? "Loading…" : "Load"}
            </button>
          </div>
          {loadError && <div className="mt-1 text-[12.5px]" style={{ color: "var(--negative)" }}>{loadError}</div>}
        </div>

        {loadedProductId && (
          <>
            {notFound && (
              <div className="text-[12.5px]" style={{ color: "var(--text-6)" }}>
                No sales history or saved profile found yet for &quot;{loadedProductId}&quot; — every
                field below is UNKNOWN. Fill in what you can and save to create the profile.
              </div>
            )}

            <div className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
              <strong>Title:</strong> {product?.title ?? "UNKNOWN"} <FieldSourceBadge source={fieldSource("title")} />
            </div>

            <div>
              <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
                Category <FieldSourceBadge source={fieldSource("category")} />
              </label>
              <input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. Kitchen Appliances"
                className="w-full rounded-lg px-3 py-2 text-[13px]"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
              />
            </div>

            <div>
              <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
                Current listing price (₹) <FieldSourceBadge source={fieldSource("price_paise")} />
              </label>
              <input
                value={priceRupees}
                onChange={(e) => setPriceRupees(e.target.value)}
                placeholder="e.g. 999"
                className="w-full rounded-lg px-3 py-2 text-[13px]"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
              />
            </div>

            <div>
              <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
                Fulfillment type <FieldSourceBadge source={fieldSource("fulfillment_type")} />
              </label>
              <select
                value={fulfillmentType}
                onChange={(e) => setFulfillmentType(e.target.value as typeof fulfillmentType)}
                className="w-full rounded-lg px-3 py-2 text-[13px]"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
              >
                <option value="">— Not set —</option>
                <option value="SELLER_FULFILLED">Seller-fulfilled</option>
                <option value="MARKETPLACE_FULFILLED">Marketplace-fulfilled</option>
              </select>
            </div>

            <div>
              <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
                Keywords <FieldSourceBadge source={fieldSource("keywords")} />
              </label>
              <input
                value={keywordsInput}
                onChange={(e) => setKeywordsInput(e.target.value)}
                placeholder="e.g. non-stick, induction-safe (comma-separated)"
                className="w-full rounded-lg px-3 py-2 text-[13px]"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
              />
            </div>

            <div>
              <label className="mb-1 block text-[12.5px]" style={{ color: "var(--text-6)" }}>
                Attributes <FieldSourceBadge source={fieldSource("attributes")} />
              </label>
              <div className="flex flex-col gap-2">
                {attributes.map((row, idx) => (
                  <div key={idx} className="flex gap-2">
                    <input
                      value={row.key}
                      onChange={(e) => updateAttributeRow(idx, { key: e.target.value })}
                      placeholder="key, e.g. material"
                      className="flex-1 rounded-lg px-3 py-2 text-[13px]"
                      style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
                    />
                    <input
                      value={row.value}
                      onChange={(e) => updateAttributeRow(idx, { value: e.target.value })}
                      placeholder="value, e.g. stainless steel"
                      className="flex-1 rounded-lg px-3 py-2 text-[13px]"
                      style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
                    />
                    <button
                      type="button"
                      onClick={() => removeAttributeRow(idx)}
                      className="rounded-lg px-3 py-2 text-[12.5px] font-semibold"
                      style={{ border: "1px solid var(--border-default)", color: "var(--negative)" }}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={addAttributeRow}
                  className="w-fit text-[12px] font-semibold"
                  style={{ color: "var(--accent)" }}
                >
                  + Add attribute
                </button>
              </div>
            </div>

            <div className="text-[12.5px]" style={{ color: "var(--text-7)" }}>
              Rating and review count are not part of this form — Metrion has no way to keep a
              hand-typed value current with the marketplace, so those stay UNKNOWN by design.
            </div>

            <div>
              <button
                type="button"
                onClick={saveProfile}
                disabled={saving}
                className="w-fit rounded-lg px-4 py-2 text-[13px] font-bold"
                style={{ background: "var(--accent)", color: "var(--accent-on-fill)", opacity: saving ? 0.6 : 1 }}
              >
                {saving ? "Saving…" : "Save profile"}
              </button>
              {saveError && <div className="mt-1 text-[12.5px]" style={{ color: "var(--negative)" }}>{saveError}</div>}
              {saved && !saveError && (
                <div className="mt-1 text-[12.5px]" style={{ color: "var(--accent)" }}>Saved.</div>
              )}
            </div>
          </>
        )}
      </div>
    </Section>
  );
}

/** Checkpoint 5 — §6.15's three visibility tiers (Recommended / Other analyzed /
 * Unanalyzed) and the Accept/Reject/Promote seller-decision flow, on top of the
 * `discovery-runs` endpoints. `MockSearchProvider` (C22's locked build order — no named
 * search provider is selected until a provider record is approved) returns nothing by
 * default, so a run against real, un-fixtured data honestly completes with zero candidates;
 * this is expected, not a bug, and is called out in the empty-state copy below rather than
 * left to look broken. */
function DiscoverySection({ getToken, onAccepted }: { getToken: () => Promise<string | null>; onAccepted: () => void }) {
  const [productIdInput, setProductIdInput] = useState("");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [run, setRun] = useState<DiscoveryRunDetail | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [busyCandidateId, setBusyCandidateId] = useState<string | null>(null);
  const [lastProductId, setLastProductId] = useState<string | null>(null);

  const refreshRun = async (runId: string) => {
    setRefreshing(true);
    try {
      const token = await getToken();
      const detail = await apiFetch<DiscoveryRunDetail>(`/api/v1/ci/discovery-runs/${runId}`, token);
      setRun(detail);
    } catch (e) {
      setDecisionError(e instanceof ApiError ? e.message : "Could not refresh the discovery run");
    } finally {
      setRefreshing(false);
    }
  };

  const startRun = async () => {
    const productId = productIdInput.trim();
    if (!productId) {
      setStartError("Enter the seller product's SKU (or marketplace item id) first — fill in its Seller Product profile above if you haven't.");
      return;
    }
    setStarting(true);
    setStartError(null);
    setDecisionError(null);
    try {
      const token = await getToken();
      const started = await apiFetch<DiscoveryRunStart>("/api/v1/ci/discovery-runs", token, {
        method: "POST",
        body: JSON.stringify({ product_id: productId }),
      });
      setLastProductId(productId);
      await refreshRun(started.discoveryRunId);
    } catch (e) {
      setStartError(e instanceof ApiError ? e.message : "Could not start discovery");
      setRun(null);
    } finally {
      setStarting(false);
    }
  };

  const decide = async (candidateId: string, decision: "ACCEPT" | "REJECT") => {
    if (!run) return;
    setBusyCandidateId(candidateId);
    setDecisionError(null);
    try {
      const token = await getToken();
      await apiFetch(`/api/v1/ci/discovery-runs/${run.discoveryRunId}/candidates/${candidateId}/decision`, token, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await refreshRun(run.discoveryRunId);
      if (decision === "ACCEPT") onAccepted();
    } catch (e) {
      setDecisionError(e instanceof ApiError ? e.message : `Could not ${decision.toLowerCase()} this candidate`);
    } finally {
      setBusyCandidateId(null);
    }
  };

  const promote = async (candidateId: string) => {
    if (!run || !lastProductId) return;
    setBusyCandidateId(candidateId);
    setDecisionError(null);
    try {
      const token = await getToken();
      await apiFetch(`/api/v1/ci/discovery-runs/${run.discoveryRunId}/candidates/${candidateId}/promote`, token, {
        method: "POST",
        body: JSON.stringify({ product_id: lastProductId }),
      });
      await refreshRun(run.discoveryRunId);
    } catch (e) {
      setDecisionError(e instanceof ApiError ? e.message : "Could not promote this candidate to analysis");
    } finally {
      setBusyCandidateId(null);
    }
  };

  const renderCandidateCard = (candidate: Candidate, opts: { analyzed: boolean }) => {
    const busy = busyCandidateId === candidate.id;
    const decided = candidate.sellerDecision !== "NONE";
    return (
      <div key={candidate.id} className="mb-3 rounded border p-3" style={{ borderColor: "var(--border-1)" }}>
        <div className="text-sm font-medium" style={{ color: "var(--text-1)" }}>{candidate.candidateUrl}</div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: "var(--text-4)" }}>
          <span>Identity match: {candidate.identityMatch ?? "not yet resolved"}</span>
          <span>Evidence: {candidate.evidenceStatus === "AWAITING_EVIDENCE" ? "Approved, awaiting evidence" : "Evidence-backed"}</span>
          <span>Decision: {candidate.sellerDecision}</span>
        </div>
        {candidate.relevance && (
          <div className="mt-1 text-xs" style={{ color: "var(--text-4)" }}>
            {candidate.relevance.isProvisional ? "Discovery relevance (provisional)" : "Relevance"}: {candidate.relevance.breakdownLine}
          </div>
        )}
        {!opts.analyzed && (
          <div className="mt-1 text-xs" style={{ color: "var(--text-5)" }}>Not yet analyzed — raw search lead only.</div>
        )}
        <div className="mt-2 flex gap-2">
          {!opts.analyzed ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => promote(candidate.id)}
              className="rounded border px-2 py-1 text-xs"
              style={{ borderColor: "var(--border-1)", color: "var(--text-2)" }}
            >
              {busy ? "Promoting…" : "Promote to analysis"}
            </button>
          ) : (
            !decided && (
              <>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => decide(candidate.id, "ACCEPT")}
                  className="rounded px-2 py-1 text-xs"
                  style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
                >
                  {busy ? "…" : "Accept"}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => decide(candidate.id, "REJECT")}
                  className="rounded border px-2 py-1 text-xs"
                  style={{ borderColor: "var(--border-1)", color: "var(--text-2)" }}
                >
                  {busy ? "…" : "Reject"}
                </button>
              </>
            )
          )}
          {candidate.competitorUrlId && (
            <span className="px-2 py-1 text-xs" style={{ color: "var(--accent)" }}>Now tracked — upload evidence below to research it.</span>
          )}
        </div>
      </div>
    );
  };

  return (
    <Section title="Discover Competitors">
      <p className="mb-3 text-sm" style={{ color: "var(--text-4)" }}>
        Generates search queries from your Seller Product profile and suggests candidate competitors — never
        marketplace scraping, and search results are leads only until you accept one and submit real evidence for it.
        Manual URL entry above always remains available independent of this.
      </p>
      <div className="mb-4 flex gap-2">
        <input
          type="text"
          value={productIdInput}
          onChange={(e) => setProductIdInput(e.target.value)}
          placeholder="Your product's SKU / marketplace item id"
          className="rounded border px-2 py-1 text-sm"
          style={{ borderColor: "var(--border-1)" }}
        />
        <button
          type="button"
          disabled={starting}
          onClick={startRun}
          className="rounded px-3 py-1 text-sm"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          {starting ? "Starting…" : "Discover Competitors"}
        </button>
        {run && (
          <button
            type="button"
            disabled={refreshing}
            onClick={() => refreshRun(run.discoveryRunId)}
            className="rounded border px-3 py-1 text-sm"
            style={{ borderColor: "var(--border-1)", color: "var(--text-2)" }}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>
      {startError && <div className="mb-3 text-sm" style={{ color: "var(--negative)" }}>{startError}</div>}
      {decisionError && <div className="mb-3 text-sm" style={{ color: "var(--negative)" }}>{decisionError}</div>}

      {run && (
        <div>
          <div className="mb-3 text-xs" style={{ color: "var(--text-4)" }}>
            Run status: {run.status}
            {run.partialReason && ` (stopped early: ${run.partialReason})`}
            {run.failedReason && ` (failed: ${run.failedReason})`}
            {" — "}
            {run.rawCandidateCount} found, {run.analyzedCandidateCount} analyzed
          </div>

          {run.recommended.length === 0 && run.otherAnalyzed.length === 0 && run.unanalyzed.length === 0 && (
            <div className="text-sm" style={{ color: "var(--text-5)" }}>
              No candidates found. Automatic discovery runs against a placeholder search backend until a real search
              provider is approved (a legal/commercial decision, not yet made) — add competitors manually above in the
              meantime.
            </div>
          )}

          {run.recommended.length > 0 && (
            <div className="mb-4">
              <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-2)" }}>Recommended</div>
              {run.recommended.map((c) => renderCandidateCard(c, { analyzed: true }))}
            </div>
          )}
          {run.otherAnalyzed.length > 0 && (
            <div className="mb-4">
              <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-2)" }}>Other analyzed</div>
              {run.otherAnalyzed.map((c) => renderCandidateCard(c, { analyzed: true }))}
            </div>
          )}
          {run.unanalyzed.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-medium" style={{ color: "var(--text-2)" }}>Unanalyzed search results</div>
              {run.unanalyzed.map((c) => renderCandidateCard(c, { analyzed: false }))}
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

/** Checkpoint 6 — deterministic-engine.md §5.15.1's `compute_price_band`, wired through
 * `GET /api/v1/ci/market-overview/{product_id}`. Every row rendered here is a real,
 * persisted `MetricResult` this function only displays — no quartile/fence/outlier math
 * happens in this component. */
function MarketOverviewSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [productIdInput, setProductIdInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<MarketOverview | null>(null);

  const load = async () => {
    const productId = productIdInput.trim();
    if (!productId) {
      setError("Enter your product's SKU / marketplace item id first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const data = await apiFetch<MarketOverview>(`/api/v1/ci/market-overview/${encodeURIComponent(productId)}`, token);
      setOverview(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the market overview");
      setOverview(null);
    } finally {
      setLoading(false);
    }
  };

  const rupees = (paise: number | null) => (paise === null ? "—" : `₹${(paise / 100).toFixed(2)}`);
  const label = (basis: string | null) => {
    if (!basis) return "—";
    const match = basis.match(/PriceBand ([A-Z_]+)/);
    return match ? match[1].replace(/_/g, " ") : basis;
  };

  return (
    <Section title="Market Overview">
      <p className="mb-3 text-sm" style={{ color: "var(--text-4)" }}>
        A price-band distribution across your tracked competitors for one product — computed by Metrion&apos;s real
        calculator, never guessed. Needs at least a few tracked, evidence-backed competitors for the same product.
      </p>
      <div className="mb-3 flex gap-2">
        <input
          type="text"
          value={productIdInput}
          onChange={(e) => setProductIdInput(e.target.value)}
          placeholder="Your product's SKU / marketplace item id"
          className="rounded border px-2 py-1 text-sm"
          style={{ borderColor: "var(--border-1)" }}
        />
        <button
          type="button"
          disabled={loading}
          onClick={load}
          className="rounded px-3 py-1 text-sm"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          {loading ? "Loading…" : "Load market overview"}
        </button>
      </div>
      {error && <div className="mb-3 text-sm" style={{ color: "var(--negative)" }}>{error}</div>}
      {overview && (
        <div>
          <div className="mb-2 text-xs" style={{ color: "var(--text-4)" }}>
            {overview.trackedCompetitorCount} tracked competitor{overview.trackedCompetitorCount === 1 ? "" : "s"} eligible
            (minimum {overview.minCompetitorsRequired} required for a band)
          </div>
          {overview.rows.length === 1 && !overview.rows[0].isAvailable ? (
            <div className="text-sm" style={{ color: "var(--text-5)" }}>
              No band yet — {overview.rows[0].unavailableReason}. Raw comparisons are still available per-competitor above.
            </div>
          ) : (
            <table className="w-full text-left text-[13px]">
              <tbody>
                {overview.rows
                  .filter((r) => r.isAvailable)
                  .map((r) => (
                    <tr key={r.engineResultRef} style={{ borderTop: "1px solid var(--border-1)" }}>
                      <td className="py-1" style={{ color: "var(--text-3)" }}>{label(r.calculationBasis)}</td>
                      <td className="py-1" style={{ color: "var(--text-2)" }}>{rupees(r.valuePaise)}</td>
                      <td className="py-1 text-xs" style={{ color: "var(--text-5)" }}>{r.confidence}</td>
                      <td className="py-1 text-xs" style={{ color: "var(--text-5)" }}>
                        ref: <code>{r.engineResultRef.slice(0, 8)}</code>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Section>
  );
}

function DigestSection({ getToken }: { getToken: () => Promise<string | null> }) {
  const [digest, setDigest] = useState<DigestPreview | null>(null);
  const [days, setDays] = useState(7);

  const load = async (windowDays: number) => {
    const token = await getToken();
    const preview = await apiFetch<DigestPreview>(`/api/v1/ci/digest/preview?days=${windowDays}`, token);
    setDigest(preview);
  };

  useEffect(() => {
    (async () => {
      await load(7);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Section title="Weekly Digest (foundation — preview only, no delivery yet)">
      <div className="mb-3 flex items-center gap-2 text-[12.5px]" style={{ color: "var(--text-6)" }}>
        <span>Window:</span>
        <select
          value={days}
          onChange={(e) => {
            const d = Number(e.target.value);
            setDays(d);
            void load(d);
          }}
          className="rounded-lg px-2 py-1"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-2)" }}
        >
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>
      {digest === null ? (
        <div style={{ color: "var(--text-6)" }}>Loading…</div>
      ) : digest.competitorsWithActivity === 0 ? (
        <div style={{ color: "var(--text-6)" }}>No price or availability changes in this window.</div>
      ) : (
        <div className="flex flex-col gap-1.5 text-[12.5px]">
          {digest.entries.map((e) => (
            <div
              key={e.competitorUrlId}
              className="rounded-lg px-3 py-2"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-subtle)" }}
            >
              <span style={{ color: "var(--text-2)" }}>{e.label ?? e.competitorUrlId.slice(0, 8)}</span>
              <span style={{ color: "var(--text-5)" }}>
                {" "}
                — {e.priceIncreaseCount} increase(s), {e.priceDecreaseCount} decrease(s),{" "}
                {e.availabilityChangeCount} availability change(s), {e.thresholdBreachedCount} alert-worthy
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
