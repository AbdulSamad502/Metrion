import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { shellData, notifications, TestShell } from "@/test-support/shellMock";
import type { Layer1Alert } from "@/lib/api";
import { ALERT_WINDOW_DAYS, type NotificationsState } from "@/lib/useNotifications";

let state: NotificationsState;
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(state)}>{children}</TestShell>,
}));

import NotificationsPage from "@/app/dashboard/notifications/page";

const alert: Layer1Alert = {
  priceEventId: "a1", competitorUrlId: "c", competitorLabel: "Rival", findingType: "PRICE_CHANGE", direction: "DECREASE", deltaPct: "-8", availabilityChange: null,
  thresholdBreached: true, message: "Rival cut its price", createdAt: "2026-10-09T10:00:00Z",
  handoff: { findingId: "f", findingType: "PRICE_CHANGE", validatedFact: [], evidenceRefs: [], competitorRefs: [], implication: "Your price may look high", suggestedAction: null, createdAt: "2026-10-09T10:00:00Z", createdBy: "x" },
};
const request = (id: string, status: string) => ({ id, requestedField: `Cost of SKU ${id}`, reason: "Needed", blockingMetric: "Net margin", status, createdAt: "2026-10-08T10:00:00Z" });

beforeEach(() => { state = notifications(); window.history.replaceState(null, "", "/dashboard/notifications"); });

describe("Action Center presentation (mocked feed)", () => {
  it("does not label every alert as a confirmed risk: the badge is neutral and says only that a threshold was crossed", async () => {
    state = notifications({ alerts: [alert] });
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Rival cut its price/ }));
    const dlg = await screen.findByRole("dialog", { name: "Rival" });
    expect(within(dlg).getByText("Crossed alert threshold")).toBeInTheDocument();
    expect(within(dlg).queryByText("Alert-worthy")).toBeNull();
  });

  it("shows the known OPEN status as 'Open' and an unknown status exactly as returned", async () => {
    state = notifications({ dataRequests: [request("r1", "OPEN")] });
    const { unmount } = render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Cost of SKU r1/ }));
    const dlg = await screen.findByRole("dialog", { name: "Data request" });
    expect(within(dlg).getAllByText("Open").length).toBeGreaterThan(0);
    unmount();

    state = notifications({ dataRequests: [request("r2", "AWAITING_SELLER")] });
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Cost of SKU r2/ }));
    const dlg2 = await screen.findByRole("dialog", { name: "Data request" });
    expect(within(dlg2).getAllByText("AWAITING_SELLER").length).toBeGreaterThan(0); // not renamed, not lowercased into a made-up friendly status
    expect(within(dlg2).queryByText("Open")).toBeNull();
  });

  it("uses the readable meta style for timestamps and a right-pointing arrow on rows that open the drawer", () => {
    state = notifications({ alerts: [alert] });
    render(<NotificationsPage />);
    const row = screen.getByRole("button", { name: /Rival cut its price/ });
    const time = row.querySelector("time") as HTMLElement;
    expect(time).toHaveClass("ov-meta"); // the readable 12px meta colour, not a faint decoration token
    expect(row.querySelector(".ov-arrow")).not.toBeNull(); // the arrow points right: this row opens something
  });

  it("says one thing once: the window comes from ALERT_WINDOW_DAYS and the no-read-state notice stays", () => {
    state = notifications({ alerts: [alert], checkedAt: "2:16 PM" });
    render(<NotificationsPage />);
    expect(screen.getByText(new RegExp(`Last ${ALERT_WINDOW_DAYS} days`))).toBeInTheDocument();
    expect(screen.getByText(/Nothing is marked read/)).toBeInTheDocument();
    expect(screen.getByText(/1 item · checked 2:16 PM/)).toBeInTheDocument();
  });
});
