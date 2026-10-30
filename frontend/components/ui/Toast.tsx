"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

type ToastKind = "success" | "error";
type ToastItem = { id: number; kind: ToastKind; message: string };
type ToastApi = { success: (message: string) => void; error: (message: string) => void };

const AUTO_DISMISS_MS = 5000;
const NOOP: ToastApi = { success: () => undefined, error: () => undefined };
const ToastContext = createContext<ToastApi>(NOOP);

/** The one place a confirmed result is announced (a save the backend accepted, a failure the seller cannot fix inline). Call it only AFTER
 * the backend has answered: nothing here is optimistic. Outside a provider the calls do nothing, so a screen rendered alone stays safe. */
export const useToast = (): ToastApi => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);
  const push = useCallback((kind: ToastKind, message: string) => {
    // One at a time keeps this quiet: a newer message replaces the older one instead of stacking.
    setItems([{ id: nextId.current++, kind, message }]);
  }, []);
  const api = useMemo<ToastApi>(() => ({ success: (m) => push("success", m), error: (m) => push("error", m) }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="mt-toast-region" role="region" aria-label="Notifications">
        {items.map((t) => (
          <Toast key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function Toast({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const [paused, setPaused] = useState(false);
  const isError = item.kind === "error";
  // An error stays until dismissed: it may carry the only explanation of what went wrong. A success clears itself, and waits while it is hovered or focused.
  useEffect(() => {
    if (isError || paused) return;
    const timer = window.setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [isError, paused, onDismiss]);

  return (
    <div
      role={isError ? "alert" : "status"}
      className="mt-toast"
      data-kind={item.kind}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="mt-toast__icon" aria-hidden>
        <Icon name={isError ? "alert" : "check"} size={16} />
      </span>
      <span className="mt-toast__text">{item.message}</span>
      <button type="button" onClick={onDismiss} aria-label="Dismiss" className="mt-toast__close mt-btn mt-focus">
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}
