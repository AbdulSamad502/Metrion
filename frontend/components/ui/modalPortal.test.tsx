import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

describe("modals sit outside the card that opened them", () => {
  it("the confirmation dialog renders in <body>, so a blurred card cannot clip it, and is opaque", () => {
    const { container } = render(
      <div className="mt-panel">
        <ConfirmDialog title="Sure?" confirmLabel="Yes" busyLabel="Working…" onConfirm={() => undefined} onCancel={() => undefined}>
          Body
        </ConfirmDialog>
      </div>,
    );
    const dialog = screen.getByRole("dialog", { name: "Sure?" });
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement?.parentElement).toBe(document.body);
    expect(dialog.style.background).toContain("--bg-popover");
  });

  it("the Business details dialog renders in <body> too", async () => {
    const { BusinessDetailsDialog } = await import("@/components/profile/BusinessDetailsDialog");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ profile: null, complete: false, suggestedName: null }), { status: 200, headers: { "Content-Type": "application/json" } })));
    const { container } = render(
      <div className="mt-panel">
        <BusinessDetailsDialog onClose={() => undefined} onSaved={() => undefined} />
      </div>,
    );
    const dialog = await screen.findByRole("dialog", { name: "Business details" });
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement?.parentElement).toBe(document.body);
    vi.unstubAllGlobals();
  });
});
