"use client";

import Link from "next/link";
import { ProductVisual } from "@/components/marketing/ProductVisual";

const TRUST_POINTS = [
  { icon: "card", label: "No credit card required" },
  { icon: "check", label: "Free trial for all agents" },
  { icon: "person", label: "Built for Indian sellers" },
];

function TrustIcon({ icon }: { icon: string }) {
  if (icon === "card") {
    return (
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
        <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" stroke="var(--accent)" strokeWidth="1.3" />
        <path d="M1.5 6.5h13" stroke="var(--accent)" strokeWidth="1.3" />
      </svg>
    );
  }
  if (icon === "person") {
    return (
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
        <circle cx="8" cy="5.2" r="2.7" stroke="var(--accent)" strokeWidth="1.3" />
        <path d="M2.5 14c0-2.9 2.5-4.5 5.5-4.5s5.5 1.6 5.5 4.5" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
      <circle cx="6.5" cy="6.5" r="6.5" fill="var(--accent-fill-default)" />
      <path d="M3.8 6.7l1.7 1.7 3.7-3.9" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Locked visual direction, per the user (2026-09-18): dark base + neon Metrion green,
 * two-column hero (left-aligned copy, dashboard visual on the right) matching their
 * reference concept image. Don't drift from this palette or layout without them asking. */
export function Hero() {
  return (
    <section id="home" className="relative overflow-hidden px-6 pt-10 pb-16 sm:px-10 sm:pt-14">
      <div className="relative mx-auto grid max-w-[1440px] grid-cols-1 items-center gap-12 xl:grid-cols-[0.92fr_1.18fr] xl:gap-4">
        <div className="relative z-10 text-center xl:text-left">
          <div
            className="mt-badge-shimmer inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-mono text-[11.5px]"
            style={{
              background: "var(--accent-fill-subtle)",
              color: "var(--text-green-muted)",
              border: "1px solid var(--accent-border-subtle)",
              opacity: 0,
              animation: "mt-fade-up 0.6s ease-out 0.05s both",
            }}
          >
            <span className="mt-glow-pulse h-1.5 w-1.5 rounded-full" style={{ background: "var(--accent)" }} />
            Profit Optimization OS for Indian E-commerce Sellers
          </div>

          <h1
            className="mt-5 text-[38px] leading-[1.12] font-bold tracking-tight sm:text-[50px] xl:text-[54px]"
            style={{ color: "var(--text-hero)", letterSpacing: "-0.01em" }}
          >
            <span className="block" style={{ opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.15s both" }}>
              More Insights.
            </span>
            <span className="block" style={{ opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.28s both" }}>
              Better Decisions.
            </span>
            <span className="block" style={{ color: "var(--accent)", opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.41s both" }}>
              Higher Profits.
            </span>
          </h1>

          <p
            className="mx-auto mt-5 max-w-[480px] text-[15px] leading-relaxed sm:text-[16px] xl:mx-0"
            style={{ color: "var(--text-4)", opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.54s both" }}
          >
            Metrion is the all-in-one AI operating system that helps Indian e-commerce
            sellers find winning products, optimize pricing, manage finances and market
            smarter — all in one place.
          </p>

          <div
            className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row xl:justify-start"
            style={{ opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.67s both" }}
          >
            <Link
              href="/sign-up"
              className="mt-cta-glow flex w-full items-center justify-center gap-1.5 rounded-lg px-6 py-3.5 text-center text-[14.5px] font-bold transition-all hover:brightness-110 active:scale-[0.97] sm:w-auto"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Get started free
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                <path d="M3 7h8M8 3.5L11.5 7 8 10.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
            <a
              href="#how-it-works"
              onClick={(e) => {
                e.preventDefault();
                document.querySelector("#how-it-works")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className="flex w-full items-center justify-center gap-2 rounded-lg px-6 py-3.5 text-center text-[14.5px] font-semibold transition-colors sm:w-auto"
              style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
            >
              <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden>
                <path d="M0 0l10 6-10 6V0z" />
              </svg>
              Watch demo
            </a>
          </div>

          <div
            className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 xl:justify-start"
            style={{ opacity: 0, animation: "mt-fade-up 0.6s ease-out 0.8s both" }}
          >
            {TRUST_POINTS.map((point) => (
              <span key={point.label} className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--text-6)" }}>
                <TrustIcon icon={point.icon} />
                {point.label}
              </span>
            ))}
          </div>
        </div>

        <ProductVisual />
      </div>
    </section>
  );
}
