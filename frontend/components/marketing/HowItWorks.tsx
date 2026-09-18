"use client";

import { useScrollReveal } from "@/lib/useScrollReveal";

const STEPS = [
  {
    title: "Upload MTR / Excel",
    icon: "upload",
    kind: "upload" as const,
    items: ["Drag & drop or click to upload"],
  },
  {
    title: "AI Analysis",
    icon: "cpu",
    kind: "list" as const,
    items: ["Cleaning data", "Finding opportunities", "Generating insights"],
  },
  {
    title: "Get Results",
    icon: "spark",
    kind: "list" as const,
    items: ["Profit report", "Product recommendations", "Competitor alerts"],
  },
  {
    title: "You Decide, You Act",
    icon: "check",
    kind: "list" as const,
    items: ["Every figure is traceable", "Metrion never writes back"],
  },
];

function ArrowConnector() {
  return (
    <div className="flex flex-shrink-0 items-center justify-center px-1 sm:px-2">
      <svg width="28" height="16" viewBox="0 0 28 16" fill="none" className="hidden rotate-90 sm:block sm:rotate-0" aria-hidden>
        <path d="M1 8h22M17 2l6 6-6 6" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" opacity="0.7" />
      </svg>
      <svg width="16" height="28" viewBox="0 0 16 28" fill="none" className="sm:hidden" aria-hidden>
        <path d="M8 1v22M2 17l6 6 6-6" stroke="var(--accent)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" opacity="0.7" />
      </svg>
    </div>
  );
}

function StepIcon({ icon }: { icon: string }) {
  const common = { width: 18, height: 18, viewBox: "0 0 18 18", fill: "none" as const, "aria-hidden": true };
  if (icon === "upload") {
    return (
      <svg {...common}>
        <path d="M9 12V2.5M5.5 6L9 2.5 12.5 6" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M2.5 12v2.5a1 1 0 001 1h11a1 1 0 001-1V12" stroke="var(--accent)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (icon === "cpu") {
    return (
      <svg {...common}>
        <rect x="5" y="5" width="8" height="8" rx="1.3" stroke="var(--accent)" strokeWidth="1.3" />
        <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.5 3.5l1.4 1.4M13.1 13.1l1.4 1.4M3.5 14.5l1.4-1.4M13.1 4.9l1.4-1.4" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    );
  }
  if (icon === "spark") {
    return (
      <svg {...common}>
        <path d="M9 1.5l1.4 4.4 4.4 1.4-4.4 1.4L9 13.1l-1.4-4.4-4.4-1.4 4.4-1.4L9 1.5z" stroke="var(--accent)" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="9" cy="9" r="7" stroke="var(--accent)" strokeWidth="1.3" />
      <path d="M5.8 9.2l2.1 2.1 4.3-4.6" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function HowItWorks() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section id="how-it-works" ref={reveal} className="mt-reveal mx-auto mt-24 max-w-[1180px] px-6">
      <div className="mx-auto max-w-[560px] text-center">
        <div className="font-mono text-[12px] font-semibold tracking-[0.08em]" style={{ color: "var(--accent)" }}>
          HOW IT WORKS
        </div>
        <h2 className="mt-3 text-[28px] font-bold sm:text-[34px]" style={{ color: "var(--text-hero)" }}>
          From Data to Decisions in 4 Steps
        </h2>
        <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--text-5)" }}>
          Upload your reports, let our AI agents analyze, and get actionable insights — instantly.
        </p>
      </div>

      <div className="mt-11 flex flex-col items-stretch sm:flex-row sm:items-center sm:justify-center">
        {STEPS.map((step, i) => (
          <div key={step.title} className="flex flex-col items-stretch sm:flex-row sm:items-center">
            <div
              className="mt-hover-card w-full rounded-2xl p-5 sm:w-[220px]"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border-default)" }}
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: "var(--accent-fill-default)" }}>
                <StepIcon icon={step.icon} />
              </span>
              <div className="mt-3 text-[14px] font-bold" style={{ color: "var(--text-1)" }}>
                {step.title}
              </div>
              <div className="mt-2.5 flex flex-col gap-1.5">
                {step.items.map((item) => (
                  <div key={item} className="flex items-center gap-1.5">
                    {step.kind === "list" ? (
                      <svg width="11" height="11" viewBox="0 0 11 11" fill="none" aria-hidden className="flex-shrink-0">
                        <circle cx="5.5" cy="5.5" r="5.5" fill="var(--accent-fill-default)" />
                        <path d="M3.2 5.6l1.4 1.4 3-3.2" stroke="var(--accent)" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    ) : (
                      <span className="h-1 w-1 flex-shrink-0 rounded-full" style={{ background: "var(--text-7)" }} />
                    )}
                    <span className="text-[11.5px]" style={{ color: "var(--text-6)" }}>
                      {item}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {i < STEPS.length - 1 && <ArrowConnector />}
          </div>
        ))}
      </div>
    </section>
  );
}
