import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RichText } from "@/components/ceo/hub/RichText";
import { findingLink } from "@/lib/ceoModel";

describe("RichText (the CEO's answer markup)", () => {
  it("renders headings, bullets, bold and http(s) links, and nothing else", () => {
    render(<RichText text={"## Top 5 products\nA note.\n\n### 1. Sony WF-1000XM5 · 61/100\n- **Supplier:** [Acme Traders](https://www.indiamart.com/p/1) · IndiaMART listing\n- **Units:** not calculated"} />);
    expect(screen.getByRole("heading", { name: "Top 5 products" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /1\. Sony WF-1000XM5/ })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Acme Traders" });
    expect(link).toHaveAttribute("href", "https://www.indiamart.com/p/1");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Supplier:").tagName).toBe("STRONG");
  });

  it("never makes a link from a non-http address and never interprets HTML", () => {
    const { container } = render(<RichText text={"[bad](javascript:alert(1)) <img src=x onerror=alert(1)> **ok**"} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("renders plain text without markup exactly as written", () => {
    const { container } = render(<RichText text={"Line one\nLine two"} />);
    expect(container.textContent).toBe("Line oneLine two");
  });
});

describe("one View Detailed Research button per research answer", () => {
  const f = (action_key: string, runId?: string) => ({ source: "PI" as const, action_key, status: "COMPLETE", report_ref: runId ? { runId } : null });
  it("only the saved-report finding links to the PI page; the run and the supplier lookup add no second button", () => {
    expect(findingLink(f("pi.report", "r1") as never)).toEqual({ href: "/dashboard/pi?run=r1", label: "View Detailed Research" });
    expect(findingLink(f("pi.discover") as never)).toBeNull();
    expect(findingLink(f("pi.supplier_lookup") as never)).toBeNull();
  });
});
