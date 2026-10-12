import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TabPanel } from "@/components/ui/Tabs";

describe("TabPanel", () => {
  it("is a keyboard stop that carries the visible focus ring", () => {
    render(<TabPanel id="a" active="a" idPrefix="t">content</TabPanel>);
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("tabindex", "0");
    expect(panel).toHaveClass("mt-focus");
  });
});
