import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { DetailDrawer } from "@/components/ui/DetailDrawer";

function Harness() {
  const [open, setOpen] = useState(false);
  const [n, setN] = useState(0);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open details</button>
      {/* an inline handler on purpose: a new function every render must not disturb focus */}
      <DetailDrawer open={open} onClose={() => setOpen(false)} title="Alert details">
        <button onClick={() => setN(n + 1)}>First action ({n})</button>
        <button>Last action</button>
      </DetailDrawer>
    </div>
  );
}

describe("DetailDrawer keyboard behaviour", () => {
  it("moves focus in, keeps Tab inside, closes on Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open details" });
    await user.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Alert details" });
    expect(dialog).toHaveFocus();

    const close = screen.getByRole("button", { name: "Close details" });
    const last = screen.getByRole("button", { name: "Last action" });
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(last).toHaveFocus();
    await user.tab(); // wraps instead of leaving the dialog
    expect(close).toHaveFocus();
    await user.tab({ shift: true }); // and wraps backwards
    expect(last).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(opener).toHaveFocus();
  });

  it("does not steal focus back when the parent re-renders with a new onClose", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open details" });
    await user.click(opener);
    await user.click(await screen.findByRole("button", { name: /First action/ })); // re-renders the parent: a new inline onClose
    expect(screen.getByRole("button", { name: /First action \(1\)/ })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(opener).toHaveFocus(); // the opener is still the page button, not something inside the drawer
  });
});
