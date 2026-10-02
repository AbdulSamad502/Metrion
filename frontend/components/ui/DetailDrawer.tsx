"use client";

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";

/** Right-hand detail panel (docs/design/frontend-design drawer behavior). A real dialog:
 * focus moves in on open and returns to the opener on close, Esc closes, the scrim is
 * clickable, and it slides with a short transition that reduced-motion turns off. */
export function DetailDrawer({
  open,
  onClose,
  title,
  subtitle,
  status,
  size = "md",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  /** A StatusBadge (or similar) shown under the title. */
  status?: ReactNode;
  /** `wide` for data-heavy content (tables); both are full-width on small screens. */
  size?: "md" | "wide";
  children: ReactNode;
}) {
  // Hydration-safe "are we on the client": false during SSR and the first client render, then true.
  const onClient = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const panelRef = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      openerRef.current?.focus?.();
    };
  }, [open, onClose]);

  // Rendered into <body> so no ancestor with a transform / backdrop-filter (every glass surface, the
  // tab-panel fade) can become the containing block of this fixed drawer and clip or offset it.
  if (!onClient) return null;
  return createPortal(
    <>
      <div className="mt-drawer-scrim" data-open={open} onClick={onClose} aria-hidden />
      <div
        ref={panelRef}
        className={`mt-drawer-panel outline-none ${size === "wide" ? "mt-drawer-panel--wide" : ""}`}
        data-open={open}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-hidden={!open}
        tabIndex={-1}
        inert={!open}
      >
        <div className="flex items-start gap-3 px-5 py-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
          <div className="min-w-0 flex-1">
            <div className="t-section truncate" style={{ color: "var(--text-1)" }}>
              {title}
            </div>
            {subtitle && (
              <div className="mt-0.5 t-body-sm" style={{ color: "var(--text-5)" }}>
                {subtitle}
              </div>
            )}
            {status && <div className="mt-2">{status}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close details" className="mt-btn mt-focus rounded-lg p-1.5" style={{ color: "var(--text-5)" }}>
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{open ? children : null}</div>
      </div>
    </>,
    document.body,
  );
}
