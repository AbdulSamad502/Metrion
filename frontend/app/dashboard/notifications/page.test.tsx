import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { shellData, notifications, TestShell } from "@/test-support/shellMock";
import type { Layer1Alert } from "@/lib/api";
import type { NotificationsState } from "@/lib/useNotifications";

let state: NotificationsState;
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(state)}>{children}</TestShell>,
}));

import NotificationsPage from "@/app/dashboard/notifications/page";

const alert = (id: string, over: Partial<Layer1Alert> = {}): Layer1Alert => ({
  priceEventId: id, competitorUrlId: "c", competitorLabel: `Rival ${id}`, findingType: "PRICE_CHANGE", direction: "DECREASE", deltaPct: "-5", availabilityChange: null,
  thresholdBreached: true, message: `Rival ${id} cut its price`, createdAt: "2026-10-09T10:00:00Z",
  handoff: { findingId: "f", findingType: "PRICE_CHANGE", validatedFact: [{ fact: "Price fell to the lower figure", confidence: "HIGH", capturedAt: "2026-10-09T09:00:00Z", isStale: true }], evidenceRefs: [], competitorRefs: [],
    implication: "Your margin at the old price may be thinner than you think", suggestedAction: { targetAgent: "CFO", suggestedQuestion: "What is my margin if I match it?" }, createdAt: "2026-10-09T10:00:00Z", createdBy: "x" },
  ...over,
});
const request = (id: string, status = "OPEN", at = "2026-10-08T10:00:00Z") => ({ id, requestedField: `Cost of SKU ${id}`, reason: "Needed to compute margin", blockingMetric: "Net margin", status, createdAt: at });

beforeEach(() => { state = notifications(); window.history.replaceState(null, "", "/dashboard/notifications"); });

describe("Action Center", () => {
  it("shows a loading state while either source is loading", () => {
    state = notifications({ alertsStatus: "loading" });
    render(<NotificationsPage />);
    expect(screen.getAllByRole("status")[0]).toHaveAttribute("aria-busy", "true");
  });

  it("is empty in plain words when nothing needs attention", () => {
    render(<NotificationsPage />);
    expect(screen.getByText("You're all caught up")).toBeInTheDocument();
  });

  it("lists alerts and only OPEN data requests, newest first, with counts on the tabs", () => {
    state = notifications({ alerts: [alert("a1")], dataRequests: [request("r1"), request("r2", "RESOLVED"), request("r3", "OPEN", "2026-10-10T10:00:00Z")] });
    render(<NotificationsPage />);
    const items = within(screen.getByRole("tabpanel")).getAllByRole("button").map((b) => b.textContent ?? "");
    expect(items).toHaveLength(3);
    expect(items[0]).toContain("Cost of SKU r3"); // newest
    expect(items[1]).toContain("Rival a1 cut its price");
    expect(items.join(" ")).not.toContain("r2"); // resolved is not shown
    expect(screen.getByRole("tab", { name: /All/ })).toHaveTextContent("3");
    expect(screen.getByRole("tab", { name: /Competitor alerts/ })).toHaveTextContent("1");
    expect(screen.getByRole("tab", { name: /Data requests/ })).toHaveTextContent("2");
  });

  it("switches tabs and shows that tab's own empty state", async () => {
    state = notifications({ alerts: [alert("a1")] });
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("tab", { name: /Data requests/ }));
    expect(await screen.findByText("No open data requests")).toBeInTheDocument();
  });

  it("names a failed source, offers a retry, and says when a role cannot see alerts", async () => {
    const reload = vi.fn();
    state = notifications({ alertsError: "boom", alertsStatus: "error", dataRequestsStatus: "forbidden", reload });
    render(<NotificationsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("Competitor alerts: boom");
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("explains a forbidden alerts source as a permission, not an error", () => {
    state = notifications({ alertsStatus: "forbidden" });
    render(<NotificationsPage />);
    expect(screen.getByText(/your role does not have access to Competitor Intelligence/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens an alert's details with evidence, implication, next question and a link to Competitors", async () => {
    state = notifications({ alerts: [alert("a1")] });
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Rival a1 cut its price/ }));
    const dlg = await screen.findByRole("dialog", { name: "Rival a1" });
    expect(within(dlg).getByText("Price fell to the lower figure")).toBeInTheDocument();
    expect(within(dlg).getByText("Stale")).toBeInTheDocument();
    expect(within(dlg).getByText("What is my margin if I match it?")).toBeInTheDocument();
    expect(within(dlg).getByRole("link", { name: "Open Competitors" })).toHaveAttribute("href", "/dashboard/competitors");
    expect(within(dlg).getByText(/never changes a price or a listing/)).toBeInTheDocument();
  });

  it("opens a data request with what is needed, why, and a link to the CFO", async () => {
    state = notifications({ dataRequests: [request("r1")] });
    render(<NotificationsPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: /Cost of SKU r1/ }));
    const dlg = await screen.findByRole("dialog", { name: "Data request" });
    expect(within(dlg).getByText("Net margin")).toBeInTheDocument();
    expect(within(dlg).getByRole("link", { name: "Open in CFO" })).toHaveAttribute("href", "/dashboard/cfo#anomalies");
  });
});
