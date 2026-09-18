"use client";

import { useCallback, useRef } from "react";

/** Cursor-tracked radial highlight for a card/panel — mousemove sets two CSS custom
 * properties the element's own background gradient reads (`--mt-glow-x/y`), so no
 * per-frame layout work happens here, just point tracking. */
export function usePointerGlow<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  const onMouseMove = useCallback((e: React.MouseEvent<T>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mt-glow-x", `${(((e.clientX - r.left) / r.width) * 100).toFixed(1)}%`);
    el.style.setProperty("--mt-glow-y", `${(((e.clientY - r.top) / r.height) * 100).toFixed(1)}%`);
  }, []);

  return { ref, onMouseMove };
}
