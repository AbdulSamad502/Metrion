"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { setDemo, useDemo } from "@/lib/demo/mode";

/** The permanent "this is sample data" marker (DESIGN.md: Demo content must always be visibly marked). It is a small floating label, so it changes
 * no page layout, and it is never drawn on the CEO Hub, which is never fed sample data. */
export function DemoBadge() {
  const on = useDemo();
  const pathname = usePathname();
  const shown = on && !pathname.startsWith("/dashboard/ceo-hub");
  useEffect(() => { // the page leaves room under its last card for the label, so nothing is hidden behind it
    if (!shown) return;
    document.documentElement.classList.add("mt-demo-bar");
    return () => document.documentElement.classList.remove("mt-demo-bar");
  }, [shown]);
  if (!shown) return null;
  return (
    <div
      role="status"
      className="fixed bottom-3 right-3 z-[90] flex max-w-[calc(100vw-24px)] flex-wrap items-center justify-end gap-x-2 gap-y-0 mt-demo rounded-xl px-3 py-1.5 t-meta max-sm:left-3"
      style={{ background: "var(--bg-popover)", border: "1px solid var(--warning-border)", color: "var(--text-2)", boxShadow: "var(--ov-shadow-lift, 0 6px 24px rgba(0,0,0,0.35))" }}
    >
      <span className="font-bold" style={{ color: "var(--warning)" }}>Sample data</span>
      <span style={{ color: "var(--text-4)" }}>Not your numbers. Nothing is saved.</span>
      <button type="button" onClick={() => setDemo(false)} className="mt-focus min-h-10 rounded-lg px-2 font-bold underline underline-offset-2" style={{ color: "var(--text-2)" }}>
        Turn off
      </button>
    </div>
  );
}
