"use client";

import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Keyboard behaviour a modal dialog promises with `aria-modal`: focus moves into it when it opens, Tab and Shift+Tab stay inside, Escape closes it,
 * and focus returns to whatever opened it. `ref` is the dialog's own element (give it `tabIndex={-1}`). */
export function useModalFocus(open: boolean, ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose; // the latest handler, so an inline callback does not re-run the focus effect on every render
  });

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const root = ref.current;
      if (!root) return;
      const items = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.getClientRects().length > 0);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === root || !root.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !root.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [open, ref]);
}
