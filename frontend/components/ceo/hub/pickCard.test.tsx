import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PickCard } from "@/components/ceo/hub/PickCard";
import type { PickCard as PickCardData } from "@/lib/ceo";

const card = (over: Partial<PickCardData> = {}): PickCardData => ({
  version: 2, kind: "PICK", title: "Choose the competitors to track", subtitle: "Tick up to 2", mode: "multi", maxPick: 2, selectAll: false,
  items: [1, 2, 3, 4].map((n) => ({ key: String(n), n, label: `Steel Bottle ${n}`, marketplace: "Amazon", url: `https://www.amazon.in/dp/B0LEAD0000${n}`, note: "found for your category “Water bottles”" })),
  actions: [{ id: "track", label: "Save and track", template: "track {numbers}" }],
  ...over,
});

describe("the CEO pick card", () => {
  it("lets the seller tick up to the limit, then sends the same text they could have typed", async () => {
    const onSend = vi.fn();
    render(<PickCard card={card()} disabled={false} onSend={onSend} />);
    await userEvent.click(screen.getByRole("checkbox", { name: /3\. Steel Bottle 3/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /1\. Steel Bottle 1/ }));
    expect(screen.getByRole("checkbox", { name: /2\. Steel Bottle 2/ })).toBeDisabled(); // the limit is reached: no third tick
    await userEvent.click(screen.getByRole("button", { name: "Save and track" }));
    expect(onSend).toHaveBeenCalledWith("track 1, 3");
  });

  it("cannot send with nothing ticked, and offers no tick boxes when the limit is zero", () => {
    const { unmount } = render(<PickCard card={card()} disabled={false} onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Save and track" })).toBeDisabled();
    unmount();
    render(<PickCard card={card({ maxPick: 0 })} disabled={false} onSend={vi.fn()} />);
    screen.getAllByRole("checkbox").forEach((c) => expect(c).toBeDisabled());
  });

  it("single mode is radio buttons, and an action that needs no pick (None of these) is always available", async () => {
    const onSend = vi.fn();
    render(<PickCard card={card({ mode: "single", maxPick: 1, actions: [{ id: "this", label: "Confirm", template: "this is {labels}" }, { id: "none", label: "None of these", template: "none of these", noPick: true }] })} disabled={false} onSend={onSend} />);
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /2\. Steel Bottle 2/ }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onSend).toHaveBeenCalledWith("this is Steel Bottle 2");
    await userEvent.click(screen.getByRole("button", { name: "None of these" }));
    expect(onSend).toHaveBeenLastCalledWith("none of these");
  });

  it("select all ticks every category, and an action that needs exactly one pick waits for exactly one", async () => {
    const onSend = vi.fn();
    render(<PickCard card={card({ selectAll: true, maxPick: 4, actions: [{ id: "go", label: "Find competitors", template: "{numbers}" }, { id: "stop", label: "Stop tracking", template: "stop tracking {labels}", exactly: 1 }] })} disabled={false} onSend={onSend} />);
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getByRole("button", { name: "Stop tracking" })).toBeDisabled(); // four ticked: not exactly one
    await userEvent.click(screen.getByRole("button", { name: "Find competitors" }));
    expect(onSend).toHaveBeenCalledWith("1, 2, 3, 4");
  });

  it("shows only what the backend sent: a link out to each listing and no price", () => {
    render(<PickCard card={card()} disabled={false} onSend={vi.fn()} />);
    expect(screen.getAllByRole("link", { name: "Open listing" })[0]).toHaveAttribute("href", "https://www.amazon.in/dp/B0LEAD00001");
    expect(screen.queryByText(/₹/)).not.toBeInTheDocument();
  });
});
