"use client";

import { useScrollReveal } from "@/lib/useScrollReveal";

const AGENTS = [
  {
    icon: "cube",
    title: "Product Intelligence",
    body: "Find high-demand products, analyze trends, and spot real opportunities across Amazon, Flipkart, Meesho, Google Trends and more.",
  },
  {
    icon: "shield",
    title: "Competitor Intelligence",
    body: "Track competitor pricing, get margin insights and receive WhatsApp alerts for key changes.",
  },
  {
    icon: "chart",
    title: "Full CFO",
    body: "Manage pricing, batch size, supplier ranking, GST calculations, MTR reconciliation, expenses & cashflow, and funding strategy.",
  },
  {
    icon: "megaphone",
    title: "Slim CMO",
    body: "Generate marketplace titles, keywords, bullets, images and hashtags to boost visibility and sales.",
  },
];

function AgentIcon({ icon }: { icon: string }) {
  const common = { width: 18, height: 18, viewBox: "0 0 18 18", fill: "none" as const, "aria-hidden": true };
  if (icon === "cube") {
    return (
      <svg {...common}>
        <path d="M9 1.5L16 5.4v7.2L9 16.5 2 12.6V5.4L9 1.5z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M2 5.4L9 9.3l7-3.9M9 9.3v7.2" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "shield") {
    return (
      <svg {...common}>
        <path d="M9 1.6l6 2.2v4.5c0 4-2.6 6.7-6 8.1-3.4-1.4-6-4.1-6-8.1V3.8l6-2.2z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
        <path d="M6.3 9l1.9 1.9 3.5-3.8" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "chart") {
    return (
      <svg {...common}>
        <path d="M2.5 15.5V6M8 15.5V2.5M13.5 15.5V9" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M1.5 15.5h15" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M2 10.5V7.5l10-4v11l-10-4z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M12 6.5l3.5-1.3v9.6L12 13.5" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M5 10.5v3a1.5 1.5 0 003 0v-2" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function Features() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section id="features" ref={reveal} className="mt-reveal mx-auto mt-24 max-w-[1180px] px-6">
      <div className="mx-auto max-w-[600px] text-center">
        <div className="font-mono text-[12px] font-semibold tracking-[0.08em]" style={{ color: "var(--accent)" }}>
          POWERFUL AGENTS
        </div>
        <h2 className="mt-3 text-[28px] font-bold sm:text-[34px]" style={{ color: "var(--text-hero)" }}>
          4 AI Agents. 1 Unified OS.
        </h2>
        <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--text-5)" }}>
          Each agent works on a specific business problem. Together, they run your entire
          e-commerce operation — from product research to profit optimization.
        </p>
      </div>

      <div className="mt-11 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {AGENTS.map((a) => (
          <div
            key={a.title}
            className="mt-hover-card group rounded-2xl p-5"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}
          >
            <div className="flex items-center justify-between">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: "var(--accent-fill-default)" }}>
                <AgentIcon icon={a.icon} />
              </span>
              <svg
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                aria-hidden
                className="opacity-0 transition-opacity group-hover:opacity-100"
                style={{ color: "var(--accent)" }}
              >
                <path d="M3 7h8M8 3.5L11.5 7 8 10.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="mt-3.5 text-[15px] font-bold" style={{ color: "var(--text-1)" }}>
              {a.title}
            </div>
            <div className="mt-1.5 text-[12.5px] leading-relaxed" style={{ color: "var(--text-6)" }}>
              {a.body}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
