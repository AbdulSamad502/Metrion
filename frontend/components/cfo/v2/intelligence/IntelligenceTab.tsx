"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { SectionState } from "@/components/cfo/v2/SectionState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import type { AlertsResponse, Period } from "@/lib/cfoV2/dashboard";
import { useCanAdjust } from "@/lib/cfoV2/useCanAdjust";
import { useCfoData } from "@/lib/cfoV2/useCfoData";

/** Intelligence: the signals the deterministic risk scan recorded (fixed wording, each pointing at an engine reference). The scan can be run now by someone allowed to. */
export function IntelligenceTab({ period }: { period: Period }) {
  const { getToken } = useAuth();
  const canAdjust = useCanAdjust();
  const alerts = useCfoData<AlertsResponse>("/intelligence/alerts", "limit=50");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/v1/cfo/risk-scan", await getToken(), { method: "POST", body: JSON.stringify({ as_of_date: period.end }) });
      alerts.reload();
    } catch (e) {
      setError(friendlyApiError(e, "The check could not be run"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h2 className="t-label">Recommended actions and alerts</h2>
        {canAdjust && (
          <button type="button" onClick={scan} disabled={busy}>
            {busy ? "Checking…" : "Check my data now"}
          </button>
        )}
      </div>
      {error && <ErrorNotice message={error} />}
      <SectionState state={alerts} title="alerts">
        {(d) =>
          d.items.length === 0 ? (
            <p className="t-body">Nothing to flag from the files you have uploaded so far.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {d.items.map((a) => (
                <li key={a.id} className="rounded-lg p-3 t-body" style={{ background: "var(--fill-hover)" }}>
                  <div>{a.text}</div>
                  <div className="t-meta" style={{ color: "var(--text-5)" }}>
                    {a.trustLabel} · {a.createdAt}
                  </div>
                  <Link href="/dashboard/ceo-hub" className="t-meta underline">
                    Ask the CEO about this
                  </Link>
                </li>
              ))}
            </ul>
          )
        }
      </SectionState>
    </div>
  );
}
