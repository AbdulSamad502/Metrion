"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { Sidebar } from "@/components/dashboard/Sidebar";
import { Topbar } from "@/components/dashboard/Topbar";
import { useAppSession } from "@/lib/useAppSession";
import {
  ApiError,
  apiFetch,
  apiFetchForm,
  type AgentStatus,
  type CompetitorUrl,
  type DigestPreview,
  type ListingDiffResult,
  type PriceEventItem,
  type ResearchNowResult,
  type RunLinkage,
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
  const [addError, setAddError] = useState<string | null>(null);
  const [selectedUrlId, setSelectedUrlId] = useState<string>("");

  const addUrl = async () => {
    setAddError(null);
    try {
      const token = await getToken();
      await apiFetch("/api/v1/ci/competitor-urls", token, {
        method: "POST",
        body: JSON.stringify({ url: newUrl }),
      });
      setNewUrl("");
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
            <button
              type="button"
              onClick={addUrl}
              className="rounded-lg px-4 py-2 text-[13px] font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Add
            </button>
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
            {selectedUrlId && <ResearchForm competitorUrlId={selectedUrlId} getToken={getToken} onChanged={onChanged} />}
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
        />
      )}
    </div>
  );
}

function CompetitorDetailSection({
  url,
  getToken,
  onChanged,
}: {
  url: CompetitorUrl | null;
  getToken: () => Promise<string | null>;
  onChanged: () => void;
}) {
  const [history, setHistory] = useState<SnapshotHistoryItem[] | null>(null);
  const [events, setEvents] = useState<PriceEventItem[] | null>(null);
  const [listingDiff, setListingDiff] = useState<ListingDiffResult | null>(null);
  // Lazy initializer, not an effect — the parent remounts this component (key={url.id})
  // whenever the selected competitor changes, so this only ever runs once per selection.
  const [tagsInput, setTagsInput] = useState(() => url?.tags.join(", ") ?? "");
  const [tagsSaving, setTagsSaving] = useState(false);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url?.id]);

  if (!url) return null;

  const saveTags = async () => {
    setTagsSaving(true);
    try {
      const token = await getToken();
      const tags = tagsInput.split(",").map((t) => t.trim()).filter(Boolean);
      await apiFetch(`/api/v1/ci/competitor-urls/${url.id}`, token, {
        method: "PATCH",
        body: JSON.stringify({ tags }),
      });
      onChanged();
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
          Refresh (after a new Research Now)
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
              placeholder="DIRECT_RIVAL, ASPIRATIONAL"
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
      </div>
    </Section>
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
  const [priceRupees, setPriceRupees] = useState("");
  const [availability, setAvailability] = useState<"IN_STOCK" | "OUT_OF_STOCK" | "">("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ResearchNowResult | null>(null);
  const [linkage, setLinkage] = useState<RunLinkage | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setFormError(null);
    setResult(null);
    setLinkage(null);
    try {
      const token = await getToken();
      const imageRefs: string[] = [];
      if (file) {
        const form = new FormData();
        form.append("file", file);
        const uploaded = await apiFetchForm<{ imageRef: string }>("/api/v1/ci/evidence", token, form);
        imageRefs.push(uploaded.imageRef);
      }

      const manualFields: Record<string, unknown> = {};
      if (priceRupees.trim()) manualFields.listed_price_paise = Math.round(parseFloat(priceRupees) * 100);
      if (availability) manualFields.availability = availability;

      const res = await apiFetch<ResearchNowResult>("/api/v1/ceo-hub/research-now", token, {
        method: "POST",
        body: JSON.stringify({ competitor_url_id: competitorUrlId, image_refs: imageRefs, manual_fields: manualFields }),
      });
      setResult(res);

      const linked = await apiFetch<RunLinkage>(`/api/v1/ceo-hub/runs/${res.ceoAgentRunId}`, token);
      setLinkage(linked);
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
          Screenshot (optional — automatic extraction isn&apos;t wired up yet; fill fields manually below instead)
        </label>
        <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-[13px]" style={{ color: "var(--text-3)" }} />
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
