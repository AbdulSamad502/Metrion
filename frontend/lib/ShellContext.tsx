"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { SessionResponse } from "@/lib/api";
import type { NotificationsState } from "@/lib/useNotifications";

/** What `DashboardShell` has already loaded, shared with the page it wraps so no page repeats
 * the session fetch or the notifications fetch. */
export type ShellData = {
  session: SessionResponse;
  displayName: string;
  roleLabel: string;
  notifications: NotificationsState;
};

const ShellContext = createContext<ShellData | null>(null);

export function ShellProvider({ value, children }: { value: ShellData; children: ReactNode }) {
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): ShellData {
  const v = useContext(ShellContext);
  if (!v) throw new Error("useShell() must be used inside <DashboardShell>");
  return v;
}
