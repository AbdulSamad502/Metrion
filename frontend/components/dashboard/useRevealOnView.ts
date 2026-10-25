import { useEffect } from "react";

/** Everything in the dashboards that draws itself in (cards, bars, rings, lines, pips, legends). Kept in step with the animation rules in overview.css, ci.css, pi.css and cmo.css. */
export const REVEAL_SELECTOR = [
  ".ov-rise", ".ov-bars-track > i", ".ov-meter > i", ".ov-leakbar > i", ".ov-flow-seg", ".ov-donut-sweep", ".ov-line-path", ".ov-wf-step",
  ".ci-pips i", ".ov-chart-key li", ".cmo-meter > i", ".ci-strip-band", ".ci-strip-dot", ".ci-diverge i", ".pi-bar > i",
].join(", ");

/** Draw-in animations start when the thing scrolls into view, not all at once when the page loads. The CSS (layered.css) holds every one of them at its first frame
 *  until it is marked `data-seen`; this marks each one once, the first time it is on screen. Reduced motion has no animations to hold, so nothing is done. */
export function useRevealOnView() {
  useEffect(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const root = document.documentElement;
    root.classList.add("mt-reveal");
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.setAttribute("data-seen", "");
        io.unobserve(e.target);
      }
    }, { threshold: 0, rootMargin: "0px 0px -8% 0px" });
    const seen = new WeakSet<Element>();
    const scan = () => {
      document.querySelectorAll(REVEAL_SELECTOR).forEach((el) => {
        if (seen.has(el) || el.hasAttribute("data-seen")) return;
        seen.add(el);
        io.observe(el);
      });
    };
    let frame = 0;
    const later = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; scan(); }); };
    scan();
    const mo = new MutationObserver(later);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      mo.disconnect();
      io.disconnect();
      if (frame) cancelAnimationFrame(frame);
      root.classList.remove("mt-reveal");
    };
  }, []);
}
