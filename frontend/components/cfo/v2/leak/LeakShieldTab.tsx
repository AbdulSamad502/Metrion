"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { DataTable, FigureCell, type Column } from "@/components/cfo/v2/tables/DataTable";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { CLAIM_STATE_LABEL, NEXT_CLAIM_STEPS, type LeakResponse, type LeakRow } from "@/lib/cfoV2/dashboard";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";

const WINDOW_TEXT: Record<string, string> = { OPEN: "Claim window open", CLOSING_SOON: "Claim window closing soon", EXPIRED: "Claim window ended", UNKNOWN: "Claim window not known" };

/** Leak Shield: discrepancies the reconciliation found, ordered by how soon the claim window closes. The status is what the SELLER reports about their own claim —
 * Metrion files nothing. Amazon findings are withheld until their match key is verified. */
export function LeakShieldTab() {
  const { getToken } = useAuth();
  const canAdjust = useCanAdjust();
  const [page, setPage] = useState(1);
  const state = useCfoData<LeakResponse>("/leak/findings", `page=${page}&page_size=25`);
  const [draft, setDraft] = useState<{ id: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (path: string, init?: RequestInit) => {
    setError(null);
    try {
      return await apiFetch<{ text?: string }>(`/api/v1/cfo${path}`, await getToken(), { method: "POST", ...init });
    } catch (e) {
      setError(friendlyApiError(e, "That could not be saved"));
      return null;
    }
  };

  const columns: Column<LeakRow>[] = [
    { key: "category", header: "Discrepancy", render: (r) => r.category.replaceAll("_", " ").toLowerCase() },
    { key: "marketplace", header: "Marketplace", render: (r) => (r.withheld ? `${r.marketplace} — withheld` : r.marketplace) },
    { key: "amount", header: "Discrepancy identified", render: (r) => (r.withheld ? <span title={r.withheldReason ?? ""}>Provisional — withheld</span> : <FigureCell cell={r.amount} />) },
    { key: "window", header: "Claim window", render: (r) => WINDOW_TEXT[r.windowStatus ?? "UNKNOWN"] ?? "Claim window not known" },
    { key: "claimState", header: "Your status", render: (r) => CLAIM_STATE_LABEL[r.claimState] ?? r.claimState },
    {
      key: "actions",
      header: "Actions",
      render: (r) =>
        r.withheld || !canAdjust ? null : (
          <span className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={async () => {
                const out = await act(`/leak-findings/${r.id}/claim/draft`);
                if (out?.text) {
                  setDraft({ id: r.id, text: out.text });
                  state.reload();
                }
              }}
            >
              Draft claim text
            </button>
            {(NEXT_CLAIM_STEPS[r.claimState] ?? []).map((to) => (
              <button
                key={to}
                type="button"
                onClick={async () => {
                  if (await act(`/leak-findings/${r.id}/claim/step`, { body: JSON.stringify({ to }) })) state.reload();
                }}
              >
                Mark: {CLAIM_STATE_LABEL[to] ?? to}
              </button>
            ))}
          </span>
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <h2 className="t-label">Leak Shield</h2>
      {error && <ErrorNotice message={error} />}
      <SectionState state={state} title="discrepancies">
        {(d) => (
          <>
            <p className="t-meta" style={{ color: "var(--text-5)" }}>
              {d.note}
            </p>
            <DataTable columns={columns} rows={d.items} rowKey={(r) => r.id} page={d.page} total={d.total} pageCount={d.pageCount} onSort={() => {}} onPage={setPage} caption="Discrepancies identified" emptyText="No discrepancies identified from the files you have uploaded." />
          </>
        )}
      </SectionState>
      {draft && (
        <section aria-label="Draft claim text" className="flex flex-col gap-2">
          <h3 className="t-label">Draft claim text (copy and paste it into the marketplace yourself)</h3>
          <textarea readOnly value={draft.text} rows={8} className="w-full" aria-label="Draft claim text" />
          <button type="button" onClick={() => void navigator.clipboard?.writeText(draft.text)}>
            Copy
          </button>
        </section>
      )}
    </div>
  );
}
