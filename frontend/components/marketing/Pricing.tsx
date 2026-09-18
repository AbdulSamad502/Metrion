"use client";

import Link from "next/link";
import { useScrollReveal } from "@/lib/useScrollReveal";

const INCLUDED = ["All four agents included", "Unlimited report uploads", "No credit card required"];

export function Pricing() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section id="pricing" ref={reveal} className="mt-reveal mx-auto mt-24 max-w-[720px] px-6 text-center">
      <div className="font-mono text-[12px] font-semibold tracking-[0.08em]" style={{ color: "var(--accent)" }}>
        PRICING
      </div>
      <h2 className="mt-3 text-[28px] font-bold sm:text-[34px]" style={{ color: "var(--text-hero)" }}>
        Free while we&rsquo;re in early access
      </h2>
      <p className="mt-3 text-[14px] leading-relaxed" style={{ color: "var(--text-5)" }}>
        Metrion is early. Pricing tiers will follow as the product matures — for now, every
        seller gets full access while we build alongside real sellers like you.
      </p>

      <div
        className="mt-hover-card mx-auto mt-9 max-w-[380px] rounded-2xl p-7"
        style={{ background: "var(--bg-card)", border: "1px solid var(--accent-border-default)" }}
      >
        <div className="text-[13px] font-bold tracking-[0.04em] uppercase" style={{ color: "var(--accent)" }}>
          Early access
        </div>
        <div className="mt-2 text-[32px] font-bold" style={{ color: "var(--text-hero)" }}>
          ₹0
        </div>
        <div className="mt-1 text-[12px]" style={{ color: "var(--text-6)" }}>
          during early access
        </div>
        <div className="mt-5 flex flex-col gap-2.5 text-left">
          {INCLUDED.map((item) => (
            <div key={item} className="flex items-center gap-2">
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none" aria-hidden>
                <circle cx="6.5" cy="6.5" r="6.5" fill="var(--accent-fill-default)" />
                <path d="M3.8 6.7l1.7 1.7 3.7-3.9" stroke="var(--accent)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-[12.5px]" style={{ color: "var(--text-3)" }}>
                {item}
              </span>
            </div>
          ))}
        </div>
        <Link
          href="/sign-up"
          className="mt-6 block w-full rounded-lg px-6 py-3 text-center text-[13.5px] font-bold transition-all hover:brightness-110 active:scale-[0.97]"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          Get started free
        </Link>
      </div>
    </section>
  );
}
