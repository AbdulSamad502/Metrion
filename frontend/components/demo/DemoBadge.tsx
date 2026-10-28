"use client";

import { usePathname } from "next/navigation";
import { setDemo, useDemo } from "@/lib/demo/mode";

/** The permanent "this is sample data" marker (DESIGN.md: Demo content must always be visibly marked). It sits in the page header, so it never covers
 * content, and it is never drawn on the CEO Hub, which is never fed sample data. */
export function DemoBadge() {
  const on = useDemo();
  const pathname = usePathname();
  if (!on || pathname.startsWith("/dashboard/ceo-hub")) return null;
  return (
    <div
      role="status"
      title="Not your numbers. Nothing is saved."
      className="mt-demo flex min-h-10 flex-shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3 t-meta"
      style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", color: "var(--text-2)" }}
    >
      <span className="font-bold" style={{ color: "var(--warning)" }}>Sample data</span>
      <span className="hidden xl:inline" style={{ color: "var(--text-4)" }}>Not your numbers. Nothing is saved.</span>
      <button type="button" onClick={() => setDemo(false)} className="mt-focus hidden min-h-8 rounded-lg px-1.5 font-bold underline underline-offset-2 sm:inline" style={{ color: "var(--text-2)" }}>
        Turn off
      </button>
    </div>
  );
}
