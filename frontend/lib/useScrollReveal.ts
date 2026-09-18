"use client";

import { useEffect, useRef } from "react";

/** Adds `.mt-revealed` (see globals.css `.mt-reveal`) the first time the element crosses
 * into view, then stops observing — a one-shot scroll entrance, not a repeating one.
 * Respects `prefers-reduced-motion` by revealing immediately instead of skipping the
 * class (the CSS itself also neutralizes the transition, this just avoids the observer
 * delay on top of it). */
export function useScrollReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      el.classList.add("mt-revealed");
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("mt-revealed");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return ref;
}
