"use client";

import Link from "next/link";
import { useScrollReveal } from "@/lib/useScrollReveal";

export function FinalCta() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section ref={reveal} className="mt-reveal relative px-6 py-28 text-center">
      <h2 className="relative text-[32px] font-bold tracking-tight sm:text-[42px]" style={{ color: "var(--text-hero)", letterSpacing: "-0.01em" }}>
        Start growing profitably.
      </h2>
      <p className="relative mx-auto mt-4 max-w-[440px] text-[14.5px]" style={{ color: "var(--text-5)" }}>
        No credit card required. Upload a report and see your first true-profit number in minutes.
      </p>
      <div className="relative mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
        <Link
          href="/sign-up"
          className="w-full rounded-lg px-6 py-3.5 text-center text-[14.5px] font-bold transition-all hover:brightness-110 active:scale-[0.97] sm:w-auto"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          Get started free
        </Link>
        <Link
          href="/sign-in"
          className="w-full rounded-lg px-6 py-3.5 text-center text-[14.5px] font-semibold transition-colors sm:w-auto"
          style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
        >
          Sign in
        </Link>
      </div>
    </section>
  );
}
