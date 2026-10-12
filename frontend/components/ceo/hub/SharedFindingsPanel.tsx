"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { SharedFinding, SharedFindingsList } from "@/lib/ceo";

const TRUST_TONE = { ENGINE_VERIFIED: "accent", SELLER_STATED: "neutral", AGENT_REPORTED: "warning" } as const;
const AGENT_NAMES: Record<string, string> = { PI: "Product Intelligence", CFO: "CFO", CMO: "CMO", CI: "Competitor Intelligence", CEO: "CEO" };

/** What the agents have reported to the CEO (GET /ceo/findings), separate from what the seller said ("What I remember"). Each entry carries the backend's fixed trust
 * wording: a reported-but-unchecked line is never styled or worded as verified. Figures are shown as references only; the panel shows no value and computes nothing.
 * Forgetting is a real, lasting action (the same source is not recorded again), so it asks first. Entries from agents this member cannot use appear only as a count. */
export function SharedFindingsPanel({ state, onForget, onRetry }: { state: { status: "loading" | "ready" | "error"; data: SharedFindingsList | null }; onForget: (id: string) => void; onRetry: () => void }) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const { status, data } = state;
  const items = data?.items ?? [];
  return (
    <section aria-labelledby="ceo-shared-findings" data-testid="shared-findings-panel">
      <h3 id="ceo-shared-findings" className="mb-2 mt-eyebrow">What the agents have reported</h3>
      {status === "loading" && !data ? (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }} role="status">Loading…</p>
      ) : status === "error" && !data ? (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }} role="alert" data-testid="shared-findings-error">
          This list could not be loaded. <button type="button" onClick={onRetry} className="mt-focus underline">Try again</button>
        </p>
      ) : items.length === 0 ? (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }} data-testid="shared-findings-empty">
          Nothing yet. When a specialist finishes work for you, what it noted shows here with how far it can be trusted.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {items.map((f) => (
            <FindingRow key={f.id} f={f} confirming={confirming === f.id} onAsk={() => setConfirming(f.id)} onCancel={() => setConfirming(null)} onConfirm={() => { setConfirming(null); onForget(f.id); }} />
          ))}
        </ul>
      )}
      {status === "error" && data && (
        <p className="m-0 mt-1.5 t-meta" role="alert" style={{ color: "var(--warning)" }}>
          Could not refresh this list; showing what was loaded earlier. <button type="button" onClick={onRetry} className="mt-focus underline">Try again</button>
        </p>
      )}
      {data && data.hiddenTotal > 0 && (
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-0.5 p-0" data-testid="shared-findings-hidden">
          {data.hidden.map((h) => (
            <li key={h.agent} className="t-meta" style={{ color: "var(--text-6)" }}>{h.message}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FindingRow({ f, confirming, onAsk, onCancel, onConfirm }: { f: SharedFinding; confirming: boolean; onAsk: () => void; onCancel: () => void; onConfirm: () => void }) {
  const agent = AGENT_NAMES[f.agent] ?? f.agent;
  const unresolved = f.figureRefs.filter((r) => !r.resolvable).length;
  return (
    <li data-testid={`shared-finding-${f.id}`} className="flex flex-col gap-1 rounded-lg px-3 py-2" style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-card)" }}>
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={TRUST_TONE[f.trust]}>{f.trustLabel}</StatusBadge>
        <span className="t-meta" style={{ color: "var(--text-5)" }}>{agent} · <time dateTime={f.createdAt}>{new Date(f.createdAt).toLocaleDateString()}</time></span>
      </div>
      {f.subject && <div className="t-body-sm font-semibold" style={{ color: "var(--text-1)" }}>“{f.subject}”</div>}
      <div className="t-body-sm" style={{ color: "var(--text-3)" }}>{f.text}</div>
      {f.figureRefs.length > 0 && (
        <div className="t-meta" style={{ color: "var(--text-6)" }}>
          {f.figureRefs.length} cited {f.figureRefs.length === 1 ? "figure" : "figures"}
          {unresolved > 0 && <span style={{ color: "var(--warning)" }}> · {unresolved} no longer traceable</span>}
        </div>
      )}
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2 t-meta" role="group" aria-label="Confirm forgetting" style={{ color: "var(--text-4)" }}>
          Forget this? The same source will not be recorded again.
          <button type="button" onClick={onConfirm} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--negative)", color: "var(--negative)" }}>Forget</button>
          <button type="button" onClick={onCancel} className="mt-btn mt-focus rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>Keep</button>
        </div>
      ) : (
        <div>
          <button type="button" onClick={onAsk} aria-label={`Forget: ${f.subject ?? f.text.slice(0, 40)}`} className="mt-focus t-meta font-semibold underline" style={{ color: "var(--text-4)" }}>Forget</button>
        </div>
      )}
    </li>
  );
}
