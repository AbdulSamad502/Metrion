import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";

describe("ProvenanceBadge", () => {
  const cases: [string, string][] = [
    ["VERIFIED", "Verified"],
    ["DERIVED", "Derived from verified"],
    ["MANUAL", "Seller-provided"],
    ["ESTIMATE", "Estimate"],
    ["UNAVAILABLE", "Unavailable"],
  ];

  it.each(cases)("shows the %s register in words, with a glyph and an explanation, not by colour alone", (register, label) => {
    render(<ProvenanceBadge register={register} />);
    const chip = screen.getByText(label);
    expect(chip).toHaveAttribute("data-register", register);
    expect(chip.getAttribute("title")).toMatch(/\w+/); // what it means, for hover and assistive tech
    expect(chip.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true"); // the glyph is decoration; the word is the content
  });

  it("never invents a sixth register: an unknown value is shown as unavailable-styled text with its own label and no claim of meaning", () => {
    render(<ProvenanceBadge register="MYSTERY" />);
    const chip = screen.getByText("MYSTERY");
    expect(chip).toHaveAttribute("data-register", "UNAVAILABLE");
    expect(chip).not.toHaveAttribute("title");
  });
});
