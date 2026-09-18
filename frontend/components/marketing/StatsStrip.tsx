"use client";

import { useScrollReveal } from "@/lib/useScrollReveal";

const STATS = [
  { icon: "bolt", title: "Save 90%", body: "time on research & analysis" },
  { icon: "trend", title: "Increase profit", body: "with data-driven decisions" },
  { icon: "shield", title: "Stay ahead", body: "with real-time competitor tracking" },
  { icon: "person", title: "Built for sellers", body: "by sellers, for sellers" },
];

function StatIcon({ icon }: { icon: string }) {
  const common = { width: 18, height: 18, viewBox: "0 0 18 18", fill: "none" as const, "aria-hidden": true };
  if (icon === "bolt") {
    return (
      <svg {...common}>
        <path d="M10 1.5L3.5 10.5H8.5L8 16.5L14.5 7.5H9.5L10 1.5Z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "trend") {
    return (
      <svg {...common}>
        <path d="M2 13.5l4.5-5 3 3 5.5-6.5" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M11.5 5h3.5v3.5" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "shield") {
    return (
      <svg {...common}>
        <path d="M9 1.6l6 2.2v4.5c0 4-2.6 6.7-6 8.1-3.4-1.4-6-4.1-6-8.1V3.8l6-2.2z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="9" cy="5.8" r="3" stroke="var(--accent)" strokeWidth="1.3" />
      <path d="M2.8 16c0-3.3 2.8-5 6.2-5s6.2 1.7 6.2 5" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function StatsStrip() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <div ref={reveal} className="mt-reveal mx-auto mt-16 max-w-[1180px] px-6 py-7" style={{ borderTop: "1px solid var(--border-subtle)", borderBottom: "1px solid var(--border-subtle)" }}>
      <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
        {STATS.map((s) => (
          <div key={s.title} className="flex items-center gap-3">
            <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--accent-fill-default)" }}>
              <StatIcon icon={s.icon} />
            </span>
            <div className="min-w-0">
              <div className="text-[13.5px] font-bold" style={{ color: "var(--text-1)" }}>
                {s.title}
              </div>
              <div className="truncate text-[11px]" style={{ color: "var(--text-6)" }}>
                {s.body}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
