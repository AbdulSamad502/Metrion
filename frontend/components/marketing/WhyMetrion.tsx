"use client";

import { useScrollReveal } from "@/lib/useScrollReveal";

const PILLARS = [
  {
    title: "Contribution profit, not revenue",
    body: "Revenue dashboards flatter you. Metrion nets out marketplace fees, ad spend, returns and cost of goods so you see what you actually keep.",
  },
  {
    title: "No LLM math, ever",
    body: "Every rupee figure is computed by a deterministic, unit-tested engine. The AI explains a number and caveats it — it never originates or re-derives one.",
  },
  {
    title: "Upload only, zero write access",
    body: "No marketplace API integration touches your account. You upload reports; Metrion reads them. Nothing is ever written back automatically.",
  },
  {
    title: "Recommend-only, you decide",
    body: "Metrion tells you what to do and why — pause a SKU, adjust a price, cut a campaign. You take the action, on your own terms, in your own seller panel.",
  },
];

export function WhyMetrion() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section id="why-metrion" ref={reveal} className="mt-reveal mx-auto mt-24 max-w-[1100px] px-6">
      <div className="mx-auto max-w-[560px] text-center">
        <div className="font-mono text-[12px] tracking-[0.05em]" style={{ color: "var(--text-7)" }}>
          WHY METRION
        </div>
        <h2 className="mt-3 text-[28px] font-bold sm:text-[32px]" style={{ color: "var(--text-hero)" }}>
          Built so you can trust every number
        </h2>
      </div>

      <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {PILLARS.map((p) => (
          <div
            key={p.title}
            className="mt-hover-card rounded-2xl p-6"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}
          >
            <div className="flex items-center gap-2.5">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: "var(--accent-fill-default)" }}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                  <path d="M3 7.3l2.6 2.6L11 4" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <div className="text-[15.5px] font-bold" style={{ color: "var(--text-1)" }}>
                {p.title}
              </div>
            </div>
            <div className="mt-3 text-[13px] leading-relaxed" style={{ color: "var(--text-6)" }}>
              {p.body}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
