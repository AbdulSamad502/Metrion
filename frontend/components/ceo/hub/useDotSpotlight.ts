import { useEffect, type RefObject } from "react";

/** Interactive things in the hub that get the dot-grid hover (disabled controls never react). */
const AREA = '[data-testid="work-area"]'; // the effect belongs to the agents view only
const HOT = 'button:not(:disabled), a[href], [role="button"], [role="tab"], .mt-glow-card, .mt-chip';
const LAG = 0.32; // how much of the distance to the pointer is closed each frame: the glow trails the cursor a little and settles
const IDLE_MS = 700;

/** The CEO Hub's hover effect (see ceo.css): a faint dot grid whose dots darken in a soft circle that trails the pointer, on the page and inside whatever
 *  button or card the pointer is over. Pointer devices only; with reduced motion the circle follows the pointer exactly and nothing fades.
 *  Display only: it sets CSS variables and a data attribute and touches no state or behaviour of the hub. */
export function useDotSpotlight(rootRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof window === "undefined" || typeof window.matchMedia !== "function" || !window.matchMedia("(hover: hover)").matches) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let tx = 0, ty = 0, x = 0, y = 0, raf = 0, idle = 0, seen = false;
    let hot: HTMLElement | null = null;

    const prime = (el: HTMLElement) => { if (!el.hasAttribute("data-dots")) el.setAttribute("data-dots", getComputedStyle(el).position === "static" ? "static" : "set"); }; // an element already positioned (absolute, sticky…) keeps its position
    const setHot = (el: HTMLElement | null) => {
      if (hot === el) return;
      if (hot) { hot.removeAttribute("data-hot"); hot.style.removeProperty("--lx"); hot.style.removeProperty("--ly"); }
      hot = el;
      if (el) {
        prime(el);
        el.setAttribute("data-hot", "");
      }
    };
    /** The pointer is in screen pixels; the hub may be drawn zoomed (the app is shown at 80%, the hub at 80% of that), so convert with the real scale. */
    const paint = () => {
      const rr = root.getBoundingClientRect();
      const k = root.offsetWidth > 0 ? rr.width / root.offsetWidth : 1;
      root.style.setProperty("--mx", `${(x - rr.left) / k}px`);
      root.style.setProperty("--my", `${(y - rr.top) / k}px`);
      if (hot) {
        const r = hot.getBoundingClientRect();
        const kh = hot.offsetWidth > 0 ? r.width / hot.offsetWidth : k;
        hot.style.setProperty("--lx", `${(x - r.left) / kh}px`);
        hot.style.setProperty("--ly", `${(y - r.top) / kh}px`);
      }
    };
    const tick = () => {
      x += (tx - x) * LAG; y += (ty - y) * LAG;
      paint();
      raf = Math.hypot(tx - x, ty - y) > 0.5 ? requestAnimationFrame(tick) : 0;
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      tx = e.clientX; ty = e.clientY;
      if (!seen || still) { x = tx; y = ty; seen = true; paint(); } else if (!raf) raf = requestAnimationFrame(tick);
      root.setAttribute("data-spot", "on");
      window.clearTimeout(idle);
      idle = window.setTimeout(() => root.removeAttribute("data-spot"), IDLE_MS);
      const t = (e.target as Element | null)?.closest?.(HOT) as HTMLElement | null;
      setHot(t && t.closest(AREA) ? t : null);
    };
    const focus = (e: FocusEvent) => { const t = (e.target as Element | null)?.closest?.(HOT) as HTMLElement | null; if (t && t.closest(AREA)) prime(t); }; // keyboard focus shows the grid too
    const leave = () => { root.removeAttribute("data-spot"); setHot(null); };

    window.addEventListener("pointermove", move, { passive: true });
    root.addEventListener("pointerleave", leave);
    root.addEventListener("focusin", focus);
    return () => {
      window.removeEventListener("pointermove", move);
      root.removeEventListener("pointerleave", leave);
      root.removeEventListener("focusin", focus);
      window.clearTimeout(idle);
      if (raf) cancelAnimationFrame(raf);
      setHot(null);
      root.removeAttribute("data-spot");
    };
  }, [rootRef]);
}
