import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HealthStrip } from "./HealthStrip";

const failed = { status: "error" as const, entries: [] };

describe("HealthStrip retry", () => {
  it("says it is trying again and cannot be pressed twice while a retry is in flight", () => {
    render(<HealthStrip health={failed} onRefresh={() => undefined} refreshing />);
    const b = screen.getByRole("button", { name: /Trying again/ });
    expect(b).toBeDisabled();
  });
  it("is an ordinary Try again button otherwise", () => {
    render(<HealthStrip health={failed} onRefresh={() => undefined} />);
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
