import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useClerk: () => ({ signOut: vi.fn() }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));
vi.mock("next/image", () => ({ default: (p: { alt: string }) => <span role="img" aria-label={p.alt} /> }));

import { Sidebar } from "@/components/dashboard/Sidebar";

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open navigation</button>
      <a href="#outside">Outside link</a>
      <Sidebar userName="Asha Rao" roleLabel="Owner" attentionCount={0} collapsed={false} onToggleCollapsed={() => undefined} mobileOpen={open} onCloseMobile={() => setOpen(false)} />
    </>
  );
}

beforeAll(() => { vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} }); });

describe("mobile navigation drawer keyboard behaviour", () => {
  it("moves focus into the drawer when it opens, keeps Tab inside, and returns focus to the opener on Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open navigation" });
    opener.focus();
    await user.keyboard("{Enter}");
    const drawer = screen.getByLabelText("Primary");
    expect(drawer.contains(document.activeElement)).toBe(true); // focus moved into the drawer, not left on the opener
    for (let i = 0; i < 30; i++) {
      await user.tab();
      expect(drawer.contains(document.activeElement)).toBe(true); // never reaches the page behind
    }
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(drawer.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(opener).toHaveFocus();
  });
});
