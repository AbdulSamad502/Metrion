"use client";

import { useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { ModalPortal } from "@/components/ui/ModalPortal";
import { useModalFocus } from "@/lib/useModalFocus";

/** Asks once before an action that changes what Metrion calculates from here on. Say what will happen, in plain words, and what it does not do.
 * Focus moves in, Tab stays inside, Escape and Cancel close it, and focus returns to the button that opened it. While the action runs the
 * dialog stays open and cannot be dismissed, so the outcome is never hidden. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busyLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useModalFocus(true, ref, () => {
    if (!busy) onCancel();
  });
  return (
    <ModalPortal>
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4" style={{ background: "var(--ov-scrim, rgba(0,0,0,0.65))" }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="confirm-title" className="mt-panel w-full max-w-md outline-none" style={{ padding: 24, background: "var(--bg-popover)", border: "1px solid var(--border-default)" }}>
        <h2 id="confirm-title" className="t-section" style={{ color: "var(--text-1)" }}>
          {title}
        </h2>
        <div className="mt-2 t-body" style={{ color: "var(--text-4)" }}>
          {children}
        </div>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={busy} className="sm:w-auto">
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm} loading={busy} loadingText={busyLabel} className="sm:w-auto">
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
    </ModalPortal>
  );
}
