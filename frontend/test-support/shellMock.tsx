import type { ReactNode } from "react";
import { ShellProvider, type ShellData } from "@/lib/ShellContext";
import type { NotificationsState } from "@/lib/useNotifications";

/** A signed-in shell for page tests: what `DashboardShell` would have loaded, with the notifications feed under the test's control. */
export const notifications = (over: Partial<NotificationsState> = {}): NotificationsState => ({
  alerts: [], alertsStatus: "ok", alertsError: null, dataRequests: [], dataRequestsStatus: "ok", dataRequestsError: null, attentionCount: 0, reload: () => undefined, ...over,
});

export const shellData = (n: NotificationsState): ShellData => ({
  session: { appUserId: "u", emailVerified: true, tenantId: "t", membershipStatus: "ACTIVE", role: "OWNER", onboardingState: "ACTIVE" },
  displayName: "Asha Rao", roleLabel: "Owner", notifications: n,
});

export function TestShell({ value, children }: { value: ShellData; children: ReactNode }) {
  return <ShellProvider value={value}>{children}</ShellProvider>;
}
