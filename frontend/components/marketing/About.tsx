"use client";

import { useScrollReveal } from "@/lib/useScrollReveal";

export function About() {
  const reveal = useScrollReveal<HTMLDivElement>();

  return (
    <section id="about" ref={reveal} className="mt-reveal mx-auto mt-24 max-w-[760px] px-6 text-center">
      <div className="font-mono text-[12px] font-semibold tracking-[0.08em]" style={{ color: "var(--accent)" }}>
        ABOUT METRION
      </div>
      <h2 className="mt-3 text-[26px] font-bold sm:text-[30px]" style={{ color: "var(--text-hero)" }}>
        Built for sellers who upload, not integrate.
      </h2>
      <p className="mt-4 text-[14.5px] leading-relaxed" style={{ color: "var(--text-5)" }}>
        Metrion doesn&rsquo;t connect to your Amazon, Flipkart or Meesho account. You upload
        the reports they already give you, and Metrion turns them into true contribution
        profit, the leaks costing you money, and what to do next — recommend-only, never
        writing back to a marketplace on its own. No marketplace API risk, no write access,
        no guessing.
      </p>
    </section>
  );
}
