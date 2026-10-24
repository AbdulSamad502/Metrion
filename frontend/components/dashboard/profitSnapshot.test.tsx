import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProfitSnapshot } from "@/components/dashboard/ProfitSnapshot";
import type { HealthEntry, PresentationFigure } from "@/lib/ceo";
import type { HealthState } from "@/lib/useCeoHub";

/** Shapes follow `GET /ceo/state/health` (backend/src/backend/ceo/business_state.py): BS_PNL_LATEST carries figures labelled "Net realized revenue",
 * "Contribution profit" and "Marketplace fees"; every value is a string the backend already formatted. The strings below are fixtures: the page must show
 * them as given and compute nothing from them. */
const fig = (label: string, value: string, over: Partial<PresentationFigure> = {}): PresentationFigure => ({
  label, value, register: "DERIVED", as_of: "2026-10-20T08:00:00+00:00", note: null, ref: { kind: "metric_result", id: label }, ...over,
});
const present = (figures: PresentationFigure[], over: Record<string, unknown> = {}) => ({ version: 1, headline: "", figures, facts: [], gaps: [], offers: [{ key: "x", label: "Ask more" }], ...over });
const pnl = (over: Partial<HealthEntry> = {}): HealthEntry => ({
  key: "BS_PNL_LATEST", status: "AVAILABLE", period: "September 2026", asOf: "2026-10-20T08:00:00+00:00", previewHint: null,
  presentation: present([fig("Net realized revenue", "₹4,25,000"), fig("Contribution profit", "₹1,20,500", { register: "VERIFIED", note: "Before owner drawings" }), fig("Marketplace fees", "₹31,000")]),
  ...over,
});
const bands = (): HealthEntry => ({ key: "BS_HEALTH_BANDS", status: "AVAILABLE", period: "September 2026", asOf: "2026-10-20T08:00:00+00:00", previewHint: null, presentation: present([fig("Contribution margin", "WATCH")]) });
const state = (entries: HealthEntry[], status: HealthState["status"] = "ready"): HealthState => ({ status, entries });
const show = (health: HealthState, over: { onRefresh?: () => void; refreshing?: boolean; checkedAt?: string | null } = {}) =>
  render(<ProfitSnapshot health={health} onRefresh={over.onRefresh ?? (() => undefined)} refreshing={over.refreshing ?? false} checkedAt={over.checkedAt ?? null} />);

describe("Profit snapshot", () => {
  it("makes the backend's Contribution profit the headline and shows its register, period and as-of date, verbatim", () => {
    show(state([pnl(), bands()]));
    const hero = screen.getByTestId("profit-hero");
    const first = within(hero).getAllByTestId("snapshot-figure")[0];
    expect(first).toHaveTextContent("Contribution profit");
    expect(first).toHaveTextContent("₹1,20,500");
    expect(first).toHaveTextContent("Verified");
    expect(first).toHaveTextContent("as of 2026-10-20");
    expect(first).toHaveTextContent("Before owner drawings"); // the backend's own note
    expect(hero).toHaveTextContent("September 2026");
  });

  it("shows the other saved figures as given and never adds or derives one", () => {
    show(state([pnl(), bands()]));
    const others = screen.getByTestId("snapshot-others");
    expect(others).toHaveTextContent("Net realized revenue");
    expect(others).toHaveTextContent("₹4,25,000");
    expect(others).toHaveTextContent("Marketplace fees");
    expect(others).toHaveTextContent("₹31,000");
    const all = screen.getAllByTestId("snapshot-figure").map((n) => n.textContent ?? "");
    expect(all.join(" ")).not.toMatch(/margin %|growth|vs last|forecast|\+\d/i); // no invented trend or ratio
    expect(screen.getAllByTestId("snapshot-figure")).toHaveLength(3); // exactly the three the backend sent
  });

  it("keeps the health bands entry as the backend presented it, beside the headline", () => {
    show(state([pnl(), bands()]));
    const card = screen.getByTestId("health-BS_HEALTH_BANDS");
    expect(card).toHaveTextContent("Contribution margin");
    expect(card).toHaveTextContent("WATCH");
  });

  it("drops the 'you could also ask' chips, which are not actions on this page", () => {
    show(state([pnl(), bands()]));
    expect(screen.queryByText("Ask more")).toBeNull();
  });

  it("marks a negative backend value in the negative tone without changing the text", () => {
    show(state([pnl({ presentation: present([fig("Contribution profit", "-₹5,000")]) })]));
    const v = within(screen.getByTestId("profit-hero")).getAllByTestId("figure-value")[0];
    expect(v).toHaveTextContent("-₹5,000");
    expect(v.getAttribute("style")).toContain("var(--negative)");
  });

  it("labels a partial result and shows the backend's own gap instead of a number it did not send", () => {
    const partial = pnl({ status: "PARTIAL", presentation: present([fig("Contribution profit", "₹1,20,500")], { gaps: ["Marketplace fees has not been computed for September 2026."] }) });
    show(state([partial]));
    const hero = screen.getByTestId("profit-hero");
    expect(hero).toHaveTextContent("partial");
    expect(hero).toHaveTextContent("Marketplace fees has not been computed for September 2026.");
    expect(within(hero).queryByText("Marketplace fees")).toBeNull();
  });

  it("shows no headline when the backend sent no Contribution profit, and falls back to its own message", () => {
    show(state([{ key: "BS_PNL_LATEST", status: "UNAVAILABLE", period: null, asOf: null, previewHint: "Upload reports first.", presentation: null }]));
    expect(screen.queryByTestId("profit-hero")).toBeNull();
    expect(screen.getByTestId("health-strip")).toHaveTextContent("Upload reports first.");
  });

  it("says how current the results are once, not twice", () => {
    show(state([pnl(), bands()]));
    expect(screen.getAllByTestId("data-freshness")).toHaveLength(1);
    expect(screen.getAllByTestId("data-freshness-badge")).toHaveLength(1);
  });

  it("shows a loading state while the first read is in flight, with no figure", () => {
    show(state([], "loading"));
    expect(screen.getByTestId("health-loading")).toBeInTheDocument();
    expect(screen.getByTestId("data-freshness")).toHaveTextContent("Checking your saved results…");
    expect(screen.queryByTestId("profit-hero")).toBeNull();
  });

  it("says nothing is saved yet, with the next step, and does not call it a failure", () => {
    show(state([]));
    const empty = screen.getByTestId("health-none-saved");
    expect(empty).toHaveTextContent("Nothing saved yet");
    expect(within(empty).getByRole("link", { name: "Upload reports" })).toHaveAttribute("href", "/dashboard/cfo#import");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers a retry when nothing loaded, and shows no figure", async () => {
    const onRefresh = vi.fn();
    show(state([], "error"), { onRefresh });
    const box = screen.getByTestId("health-unavailable");
    await userEvent.setup().click(within(box).getByRole("button", { name: "Retry" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("profit-hero")).toBeNull();
  });

  it("keeps the last results on screen when a refresh fails, and says so", () => {
    show(state([pnl(), bands()], "error"));
    expect(screen.getByTestId("profit-hero")).toHaveTextContent("₹1,20,500");
    expect(screen.getByRole("alert")).toHaveTextContent("Showing the last ones that loaded");
  });

  it("shows when it last checked and disables Refresh while one is running", async () => {
    const onRefresh = vi.fn();
    const { rerender } = show(state([pnl()]), { onRefresh, checkedAt: "2026-10-24T09:05:00Z" });
    expect(screen.getByText(/^Checked /)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    rerender(<ProfitSnapshot health={state([pnl()])} onRefresh={onRefresh} refreshing checkedAt="2026-10-24T09:05:00Z" />);
    expect(screen.getByRole("button", { name: /Refreshing/ })).toBeDisabled();
  });
});
