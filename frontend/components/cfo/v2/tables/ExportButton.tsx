"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { API_BASE } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";

/** Download the same query, run again on the server (csv or xlsx). The server audits it, escapes cells that could run as formulas in a spreadsheet, and scopes it
 * to the tenant; the browser only saves the bytes. */
export function ExportButton({ path, query, format, filename, label }: { path: string; query: string; format: "csv" | "xlsx"; filename: string; label: string }) {
  const { getToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      const qs = new URLSearchParams(query);
      qs.set("export", format);
      const res = await fetch(`${API_BASE}${path}?${qs.toString()}`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
      if (!res.ok) throw new Error(`Request failed with ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${filename}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(friendlyApiError(e, "The export could not be created"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-col gap-1">
      <button type="button" onClick={run} disabled={busy}>
        {busy ? "Preparing…" : label}
      </button>
      {error && (
        <span role="alert" className="t-meta" style={{ color: "var(--negative)" }}>
          {error}
        </span>
      )}
    </span>
  );
}
