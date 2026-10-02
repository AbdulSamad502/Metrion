"use client";

import Image from "next/image";
import { usePointerGlow } from "@/lib/usePointerGlow";
import { useScrollReveal } from "@/lib/useScrollReveal";

const SIDEBAR_ITEMS = ["CEO", "Product Intelligence", "Competitor Intelligence", "Full CFO", "Slim CMO", "Reports"];

const STATS = [
  { label: "Total Revenue", value: "₹6,24,000", delta: "↑ 15.3%" },
  { label: "Net Profit", value: "₹1,82,000", delta: "↑ 12.4%" },
  { label: "Margin", value: "29.2%", delta: "↑ 4.7%" },
];

const OPPORTUNITIES = [
  { name: "Wireless Earbuds", note: "High demand · Low competition", score: "92" },
  { name: "Smart Watch", note: "Growing trend · Good margin", score: "87" },
  { name: "Phone Accessories", note: "Stable demand · Avg. margin", score: "74" },
];

const CHART_POINTS = "0,64 26,52 52,58 78,34 104,40 130,20 156,26 182,8 208,14";

/** The hero's centerpiece — an illustrative recreation of the real app shell, not a live
 * data source. Numbers are fixed sample figures for a marketing mockup (never the
 * authenticated dashboard, which only ever shows real engine output or UNAVAILABLE —
 * CLAUDE.md's "no fabricated money figures" rule governs the *product*, not a pre-auth
 * landing-page illustration). Orbital rings + mountain silhouette + tilt are decorative,
 * `prefers-reduced-motion` freezes them to a static frame via globals.css. */
export function ProductVisual() {
  const reveal = useScrollReveal<HTMLDivElement>();
  const { ref: panelRef, onMouseMove: onPanelMouseMove } = usePointerGlow<HTMLDivElement>();

  return (
    <div ref={reveal} className="mt-reveal relative w-full pt-8 pb-10 lg:pt-0">
      {/* Mountain silhouette + orbital glow rings — purely decorative, bleeds left under
          the text column so the hero reads as one scene rather than two boxed halves. */}
      <div aria-hidden className="pointer-events-none absolute -inset-x-[55%] -bottom-10 -z-10 h-[560px] overflow-visible sm:-inset-x-[35%]">
        <svg viewBox="0 0 1200 300" preserveAspectRatio="none" className="absolute bottom-0 h-full w-full opacity-70">
          <path d="M0 300 L0 190 L140 90 L260 160 L380 60 L520 170 L640 40 L780 150 L900 80 L1040 180 L1200 110 L1200 300 Z" fill="#0d1a10" />
          <path d="M0 300 L0 230 L180 150 L340 210 L480 130 L620 220 L760 120 L920 210 L1080 150 L1200 200 L1200 300 Z" fill="#0a130c" />
        </svg>
        <div
          className="mt-orbit-ring absolute top-1/2 left-1/2 h-[640px] w-[640px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ border: "1px solid rgba(62,207,116,0.12)" }}
        />
        <div
          className="mt-orbit-ring-slow absolute top-1/2 left-1/2 h-[820px] w-[820px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ border: "1px solid rgba(62,207,116,0.07)" }}
        />
        <div
          aria-hidden
          className="mt-glow-pulse absolute top-1/2 left-1/2 h-[420px] w-[720px] -translate-x-1/2 -translate-y-1/2"
          style={{ background: "radial-gradient(ellipse, rgba(62,207,116,0.16), transparent 70%)" }}
        />
      </div>

      <div className="relative" style={{ perspective: "1400px" }}>
        {/* Floating insight cards */}
        <div
          className="mt-float absolute -top-5 left-0 z-20 hidden w-[200px] rounded-2xl p-4 lg:block"
          style={{
            background: "var(--bg-card-glass)",
            backdropFilter: "blur(24px) saturate(180%)",
            border: "1px solid var(--border-default)",
            boxShadow: "var(--shadow-float)",
            animationDelay: "0.2s",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold tracking-wide uppercase" style={{ color: "var(--accent)" }}>
              Product Intelligence
            </span>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
              <path d="M2 6h8M6.5 2.5L10 6 6.5 9.5" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="mt-2 text-[13px] font-semibold" style={{ color: "var(--text-2)" }}>
            New trending products found
          </div>
          <div className="mt-1 text-[11.5px] leading-snug" style={{ color: "var(--text-6)" }}>
            Wireless earbuds — high demand, low competition
          </div>
        </div>

        <div
          className="mt-float absolute -top-9 right-0 z-20 hidden w-[220px] rounded-2xl p-4 lg:block"
          style={{
            background: "var(--bg-card-glass)",
            backdropFilter: "blur(24px) saturate(180%)",
            border: "1px solid var(--accent-border-default)",
            boxShadow: "var(--shadow-float)",
            animationDelay: "0.8s",
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold tracking-wide uppercase" style={{ color: "var(--warning)" }}>
              Competitor Price Guard
            </span>
            <span className="text-[10px]" style={{ color: "var(--text-7)" }}>
              2 changes
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-[13px] font-bold line-through" style={{ color: "var(--text-7)" }}>
              ₹299
            </span>
            <span className="text-[15px] font-bold" style={{ color: "var(--accent)" }}>
              ₹279
            </span>
          </div>
          <div className="mt-1 text-[11.5px] leading-snug" style={{ color: "var(--text-6)" }}>
            Price changes detected — 2 competitors
          </div>
        </div>

        <div
          className="mt-float absolute right-4 -bottom-8 z-20 hidden w-[190px] rounded-2xl p-4 sm:block"
          style={{
            background: "var(--bg-card-glass)",
            backdropFilter: "blur(24px) saturate(180%)",
            border: "1px solid var(--border-default)",
            boxShadow: "var(--shadow-float)",
            animationDelay: "1.4s",
          }}
        >
          <div className="text-[10px] font-bold tracking-wide uppercase" style={{ color: "var(--accent)" }}>
            Full CFO
          </div>
          <div className="mt-1.5 text-[12px] font-semibold" style={{ color: "var(--text-2)" }}>
            GST &amp; P&amp;L reconciliation
          </div>
          <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px]" style={{ color: "var(--accent)" }}>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
              <circle cx="6" cy="6" r="6" fill="var(--accent-fill-default)" />
              <path d="M3.4 6.1l1.6 1.6 3.4-3.6" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Completed
          </div>
        </div>

        {/* The tilted panel itself */}
        <div
          ref={panelRef}
          onMouseMove={onPanelMouseMove}
          className="mt-glow-panel mt-tilt-panel relative overflow-hidden rounded-[18px]"
          style={{
            background: "rgba(24,27,23,0.5)",
            backdropFilter: "blur(30px) saturate(180%)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08), 0 40px 90px rgba(0,0,0,0.6)",
            border: "1px solid var(--border-default)",
          }}
        >
          <div className="flex">
            {/* Sidebar */}
            <div className="hidden w-[190px] flex-shrink-0 flex-col gap-0.5 p-3.5 sm:flex" style={{ borderRight: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-2 pt-0.5 pb-4">
                <Image src="/metrion-mark.png" alt="" width={24} height={16} />
                <div>
                  <div className="text-[13px] leading-none font-bold" style={{ color: "var(--text-1)" }}>
                    Metrion
                  </div>
                  <div className="mt-1 text-[7px] font-semibold tracking-[0.1em]" style={{ color: "var(--text-green-muted)" }}>
                    ENGINE OF GROWTH
                  </div>
                </div>
              </div>
              {SIDEBAR_ITEMS.map((item, i) => (
                <div
                  key={item}
                  className="rounded-[10px] px-2.5 py-2 text-[12px] font-medium"
                  style={{
                    color: i === 0 ? "var(--text-2)" : "var(--text-5)",
                    background: i === 0 ? "var(--accent-fill-default)" : "transparent",
                    fontWeight: i === 0 ? 600 : 500,
                  }}
                >
                  {item}
                </div>
              ))}
            </div>

            {/* Main pane */}
            <div className="relative min-w-0 flex-1 p-5 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-[19px] font-bold" style={{ color: "var(--text-1)" }}>
                    Good Morning, Seller
                  </div>
                  <div className="mt-0.5 text-[12px]" style={{ color: "var(--text-6)" }}>
                    Here&rsquo;s your business performance overview
                  </div>
                </div>
                <div
                  className="rounded-[10px] px-3.5 py-2 text-[12px] font-bold whitespace-nowrap"
                  style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
                >
                  Ask Metrion
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
                {STATS.map((s) => (
                  <div key={s.label} className="rounded-2xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}>
                    <div className="text-[10.5px] font-semibold tracking-[0.04em] uppercase" style={{ color: "var(--text-6)" }}>
                      {s.label}
                    </div>
                    <div className="mt-1.5 text-[20px] font-bold" style={{ color: "var(--text-hero)" }}>
                      {s.value}
                    </div>
                    <div className="mt-1 text-[11.5px] font-bold" style={{ color: "var(--accent)" }}>
                      {s.delta}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-3.5 grid grid-cols-1 gap-3.5 sm:grid-cols-[1.3fr_1fr]">
                <div className="rounded-2xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}>
                  <div className="flex items-center justify-between">
                    <span className="text-[12.5px] font-bold" style={{ color: "var(--text-2)" }}>
                      Profit Trend
                    </span>
                    <div className="flex gap-1">
                      {["7D", "30D", "3M"].map((t, i) => (
                        <span
                          key={t}
                          className="rounded-md px-1.5 py-0.5 text-[9.5px] font-semibold"
                          style={{
                            color: i === 0 ? "var(--accent-on-fill)" : "var(--text-7)",
                            background: i === 0 ? "var(--accent)" : "transparent",
                          }}
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                  <svg viewBox="0 0 210 72" className="mt-3 h-[72px] w-full" preserveAspectRatio="none">
                    <polyline points={CHART_POINTS} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    <polygon points={`0,72 ${CHART_POINTS} 208,72`} fill="url(#mtChartFill)" opacity="0.5" />
                    <defs>
                      <linearGradient id="mtChartFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
                        <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                  </svg>
                </div>

                <div className="rounded-2xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}>
                  <div className="text-[12.5px] font-bold" style={{ color: "var(--text-2)" }}>
                    Top Opportunities
                  </div>
                  <div className="mt-2.5 flex flex-col gap-2.5">
                    {OPPORTUNITIES.map((o) => (
                      <div key={o.name} className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-[11.5px] font-semibold" style={{ color: "var(--text-3)" }}>
                            {o.name}
                          </div>
                          <div className="truncate text-[10px]" style={{ color: "var(--text-7)" }}>
                            {o.note}
                          </div>
                        </div>
                        <span
                          className="flex-shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-bold"
                          style={{ background: "var(--accent-fill-default)", color: "var(--accent)" }}
                        >
                          {o.score}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
