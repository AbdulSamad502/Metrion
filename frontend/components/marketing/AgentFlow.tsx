"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { useScrollReveal } from "@/lib/useScrollReveal";

const AGENTS = [
  { key: "PRODUCT_AGENT", desc: "Finds pricing and demand gaps across your catalog." },
  { key: "COMPETITOR_AGENT", desc: "Reads seller-provided competitor pricing for context." },
  { key: "CFO_AGENT", desc: "Tracks margin, fees and cash against the ledger." },
  { key: "CMO_AGENT", desc: "Connects spend and campaigns to profit, not clicks." },
];

const TIMING = [
  { dur: "2.6s", begin: "1s" },
  { dur: "2.3s", begin: "1.2s" },
  { dur: "2.3s", begin: "1.4s" },
  { dur: "2.6s", begin: "1.6s" },
];

type FlowLine = { path: string; dur: string; begin: string; delay: string; pulse: boolean; midX: number; midY: number };

/** Recreates the .dc.html prototype's `measureLanding()` in React: each agent card's
 * bottom-center connects to the CEO node's top-center with a bezier curve, measured from
 * real DOM positions (not hardcoded coordinates) so it holds up across viewport widths and
 * font-load reflow. A traveling dot loops along each path continuously — "data flowing
 * into the CEO" per the brief — independent of scroll state; only the section's own
 * fade-up entrance is scroll-gated (via useScrollReveal). */
export function AgentFlow() {
  const sectionReveal = useScrollReveal<HTMLDivElement>();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const ceoRef = useRef<HTMLDivElement | null>(null);
  const nodeRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [lines, setLines] = useState<FlowLine[]>([]);

  useEffect(() => {
    function measure() {
      const wrap = wrapRef.current;
      const ceo = ceoRef.current;
      if (!wrap || !ceo) return;
      const wrapRect = wrap.getBoundingClientRect();
      const ceoRect = ceo.getBoundingClientRect();
      const tx = ceoRect.left + ceoRect.width / 2 - wrapRect.left;
      const ty = ceoRect.top - wrapRect.top;
      const next: FlowLine[] = [];
      for (let i = 0; i < AGENTS.length; i++) {
        const node = nodeRefs.current[i];
        if (!node) return;
        const r = node.getBoundingClientRect();
        const x1 = r.left + r.width / 2 - wrapRect.left;
        const y1 = r.bottom - wrapRect.top;
        const ymid = (y1 + ty) / 2;
        next.push({
          path: `M${x1},${y1} C${x1},${ymid} ${tx},${ymid} ${tx},${ty}`,
          dur: TIMING[i].dur,
          begin: TIMING[i].begin,
          delay: `${(i * 0.08).toFixed(2)}s`,
          pulse: i === 1 || i === 2,
          midX: (x1 + tx) / 2,
          midY: ymid,
        });
      }
      setLines(next);
    }

    measure();
    const timers = [0, 100, 300, 600, 900, 1300].map((t) => setTimeout(measure, t));
    window.addEventListener("resize", measure);
    let ro: ResizeObserver | undefined;
    if (window.ResizeObserver && wrapRef.current) {
      ro = new ResizeObserver(measure);
      ro.observe(wrapRef.current);
    }
    if (document.fonts?.ready) document.fonts.ready.then(measure);
    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("resize", measure);
      ro?.disconnect();
    };
  }, []);

  return (
    <section id="agents" ref={sectionReveal} className="mt-reveal relative mx-auto mt-24 max-w-[1000px] px-6">
      <div
        aria-hidden
        className="pointer-events-none absolute top-0 left-1/2 h-[520px] w-[900px] -translate-x-1/2 -translate-y-[10%]"
        style={{ background: "radial-gradient(ellipse 450px 300px at 50% 40%, rgba(62,207,116,0.1), transparent 70%)" }}
      />

      <div className="relative mx-auto max-w-[640px] text-center">
        <div className="font-mono text-[12px] tracking-[0.05em]" style={{ color: "var(--text-7)" }}>
          ONE OS, FOUR SPECIALISTS
        </div>
        <h2 className="mt-3 text-[28px] font-bold sm:text-[32px]" style={{ color: "var(--text-hero)" }}>
          You talk to one CEO. It runs four agents behind you.
        </h2>
      </div>

      <div ref={wrapRef} className="relative mt-14">
        <svg className="pointer-events-none absolute top-0 left-0 h-full w-full overflow-visible" aria-hidden>
          <defs>
            <filter id="mtLineGlow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.4" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {lines.map((ln, i) => (
            <path key={`path-${i}`} d={ln.path} stroke="rgba(62,207,116,0.4)" strokeWidth={1.3} fill="none" filter="url(#mtLineGlow)" />
          ))}
          {lines.map(
            (ln, i) =>
              ln.pulse && (
                <circle
                  key={`pulse-${i}`}
                  cx={ln.midX}
                  cy={ln.midY}
                  r={2.6}
                  fill="var(--accent)"
                  style={{ animation: `mt-node-pulse 1.8s ease-in-out ${ln.delay} infinite`, filter: "drop-shadow(0 0 3px rgba(62,207,116,0.8))" }}
                />
              ),
          )}
          {lines.map((ln, i) => (
            <circle key={`dot-${i}`} r={2.4} fill="var(--accent)">
              <animateMotion dur={ln.dur} repeatCount="indefinite" begin={ln.begin} path={ln.path} />
              <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={ln.dur} begin={ln.begin} repeatCount="indefinite" />
            </circle>
          ))}
        </svg>

        <div className="relative z-[1] grid grid-cols-2 gap-3.5 sm:flex sm:justify-between">
          {AGENTS.map((agent, i) => (
            <div
              key={agent.key}
              ref={(el) => {
                nodeRefs.current[i] = el;
              }}
              className="mt-hover-card rounded-2xl p-4 sm:w-[190px]"
              style={{
                background: "var(--bg-card)",
                backdropFilter: "blur(22px) saturate(150%)",
                boxShadow: "inset 0 1px 0 rgba(255,255,255,0.06)",
                border: "1px solid var(--border-default)",
              }}
            >
              <div className="font-mono text-[12px] font-semibold" style={{ color: "var(--accent)" }}>
                {agent.key}
              </div>
              <div className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--text-6)" }}>
                {agent.desc}
              </div>
            </div>
          ))}
        </div>

        <div className="relative z-[1] mt-9 flex justify-center">
          <div
            ref={ceoRef}
            className="flex flex-col items-center gap-2.5 rounded-2xl px-8 py-[18px]"
            style={{
              background: "radial-gradient(circle at 30% 25%, #1C3D28, #0B140E)",
              border: "1px solid rgba(62,207,116,0.5)",
              animation: "mt-ceo-pulse 2.6s ease-in-out infinite",
            }}
          >
            <Image src="/metrion-mark.png" alt="" width={26} height={26} />
            <div className="text-[15px] font-bold whitespace-nowrap" style={{ color: "var(--text-1)" }}>
              CEO Agent
            </div>
            <div className="font-mono text-[10.5px] tracking-[0.04em]" style={{ color: "var(--text-green-muted)" }}>
              one recommendation, four inputs
            </div>
          </div>
        </div>
      </div>

      <div className="mt-10 text-center font-mono text-[12.5px]" style={{ color: "var(--text-8)" }}>
        every line above resolves to one verified number — nothing here is a language model&rsquo;s guess.
      </div>
    </section>
  );
}
