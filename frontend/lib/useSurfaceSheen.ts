"use client";

import { useEffect, type RefObject } from "react";

/** Cards larger than this (px²) are layout containers (the Hub's columns), not cards: they get no hover sheen. */
const MAX_AREA = 380_000;

/** A soft, cursor-following highlight on the glass card under a mouse. One delegated listener on the shell root, throttled to a frame, writing two CSS
 * variables on the single hovered card; nothing re-renders. It does nothing for touch or pen, when the visitor prefers reduced motion, or when the
 * hovered surface is a container rather than a card. The look lives in `.mt-app-surface [data-sheen]` (globals.css). */
export function useSurfaceSheen(rootRef: RefObject<HTMLElement | null>, mounted = true): void {
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof window.matchMedia !== "function") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || window.matchMedia("(hover: none)").matches) return;

    let current: HTMLElement | null = null;
    let frame = 0;
    const clear = () => {
      if (!current) return;
      current.removeAttribute("data-sheen");
      current.style.removeProperty("--mx");
      current.style.removeProperty("--my");
      current = null;
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerType && e.pointerType !== "mouse") return;
      const card = (e.target as Element | null)?.closest?.<HTMLElement>(".mt-dash-card:not(.mt-dash-card--locked), .mt-panel") ?? null;
      if (card !== current) {
        clear();
        if (card) {
          const r = card.getBoundingClientRect();
          if (r.width * r.height > MAX_AREA) return;
          current = card;
          card.setAttribute("data-sheen", "");
        }
      }
      if (!current) return;
      const { clientX, clientY } = e;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!current) return;
        const r = current.getBoundingClientRect();
        current.style.setProperty("--mx", `${(((clientX - r.left) / r.width) * 100).toFixed(1)}%`);
        current.style.setProperty("--my", `${(((clientY - r.top) / r.height) * 100).toFixed(1)}%`);
      });
    };
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", clear);
    return () => {
      cancelAnimationFrame(frame);
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", clear);
      clear();
    };
  }, [rootRef, mounted]); // `mounted`: a shell that shows a loading state first has no element on its first run, so attach when it appears
}
