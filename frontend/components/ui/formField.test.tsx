import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FormField } from "@/components/ui/FormField";

describe("FormField password toggle", () => {
  it("is reachable by keyboard, announces its state and reveals the password", async () => {
    render(<FormField label="Password" type="password" defaultValue="secret" />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    await user.tab(); // input
    await user.tab(); // the toggle: it must be in the tab order
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.keyboard("{Enter}");
    expect(input).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps a visible focus ring on the field itself (the class carrying the :focus-visible outline)", () => {
    render(<FormField label="Email" type="email" />);
    expect(screen.getByLabelText("Email")).toHaveClass("mt-focus");
  });
});
