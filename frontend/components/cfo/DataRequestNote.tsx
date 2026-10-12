"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, type DataRequestItem } from "@/lib/api";

/** What Metrion needs, in words a seller recognises. An unknown field is shown as it is stored, never guessed. */
const FIELD_WORDS: Record<string, string> = {
  "supplier.quote": "a supplier quote for this product (supplier, unit cost and quantity)",
  cogs_per_unit: "what one unit of this product costs you",
  "batch.budget": "your budget for one batch",
  "seller.goal": "your seller goal",
};

/** The fields Ask Metrion's guided input can save (mirrors SESSION_FOR_FIELD in backend/ceo/data_requests.py). For any other field no way to supply it is promised. */
const SAVABLE_IN_ASK_METRION = new Set(["supplier.quote", "cogs_per_unit", "batch.budget"]);

/** Shown after a calculation stopped because an input is missing. It says what is missing and where to give it. The calculation did not guess: it asked. Reads the
 * request back through the existing `GET /cfo/data-requests`; if that read fails, the short id is still shown so the request can be found. */
export function DataRequestNote({ id, getToken }: { id: string; getToken: () => Promise<string | null> }) {
  const [request, setRequest] = useState<DataRequestItem | null | undefined>(undefined);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const rows = await apiFetch<DataRequestItem[]>("/api/v1/cfo/data-requests", await getToken());
        if (live) setRequest(rows.find((r) => r.id === id) ?? null);
      } catch {
        if (live) setRequest(null);
      }
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const what = request ? (FIELD_WORDS[request.requestedField] ?? request.requestedField) : null;
  return (
    <div className="t-body-sm" style={{ color: "var(--text-4)" }} data-testid="data-request-note">
      {what ? (
        <>
          Not calculated: Metrion needs {what}.{request?.reason ? ` ${request.reason}` : ""}{" "}
        </>
      ) : (
        <>Not calculated: an input is missing (request <code>{id.slice(0, 8)}</code>). </>
      )}
      Nothing was assumed.
      {request && SAVABLE_IN_ASK_METRION.has(request.requestedField) && (
        <>
          {" "}Tell{" "}
          <Link href="/dashboard/ceo-hub" className="mt-focus font-semibold underline" style={{ color: "var(--text-2)" }}>
            Ask Metrion
          </Link>{" "}
          what you have and it will save it, then run this again.
        </>
      )}
    </div>
  );
}
