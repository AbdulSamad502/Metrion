import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ListingCard } from "@/components/ceo/hub/ListingCard";
import { isListingCard } from "@/lib/ceo";
import type { ListingCard as Card, ListingAuditCheck } from "@/lib/ceo";

const BANNER = "Marketplace rules are not verified for Amazon. Lengths and field limits were measured, not checked. Check them on the marketplace before you use this listing.";
const IDS = ["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10", "A11", "A12", "A13", "A14", "A15"];
const checks = (): ListingAuditCheck[] => IDS.map((id) => ({ id, name: `Check ${id}`, status: id === "A13" || id === "A15" || id === "A03" ? "NOT_ASSESSED" : id === "A12" ? "NOT_APPLICABLE" : "PASS", detail: id === "A15" ? "Spelling, grammar and writing style are not checked by Metrion." : "" }));
const card = (over: Partial<Card> = {}): Card => ({
  version: 1, kind: "LISTING", notice: "Generated, audited, approved for use, copied and marked used are separate steps. None of them means the listing is published, live, accepted or verified by any marketplace; Metrion cannot see or change what is on a marketplace.",
  investigationId: "inv-1", generationId: "gen-1", marketplace: "AMAZON", rulesBasis: "UNVERIFIED", banner: BANNER, strategy: "Brand-first", revisionOf: null,
  sections: { title: "AquaNest 1 Litre Stainless Steel Water Bottle", bullets: ["Stainless steel body", "Holds 1 litre", "Easy to carry"], description: "The AquaNest bottle holds 1 litre.", keywords: ["steel bottle", "water bottle"], backend_terms: ["steel flask"] },
  keywordMap: {
    candidates: [{ keyword: "steel bottle", placed: true, where: [{ section: "TITLE", count: 1 }, { section: "BULLET 1", count: 2 }], intent: "PRODUCT_TYPE", reason: null }, { keyword: "gym", placed: false, where: [], intent: "USE_CASE", reason: "NOT_NEEDED" }],
    notUsed: [{ keyword: "reusable", reason: "Not used: evidence is weak." }], excluded: [], limits: "Fit with your own confirmed facts and where each word appears. This is not search volume, ranking, buyer demand or conversion; those are not assessed.",
  },
  audit: {
    auditId: "a1", contentHash: "h".repeat(64), verdict: "CHECKED_NOT_VERIFIED", counts: { blockers: 0, warnings: 1, notes: 1 }, checks: checks(), method: "listing-audit-v1", createdAt: "2026-10-30T10:00:00Z",
    findings: [
      { check: "A08", severity: "WARNING", section: "BULLET 1", code: "W1_REPEATED_IN_BULLET", explanation: "“steel bottle” appears 2 times in one bullet. This is a readability check, not a marketplace or ranking rule.", correction: "Say it once." },
      { check: "A14", severity: "NOTE", section: "WHOLE_LISTING", code: "FACT_NOT_GIVEN", explanation: "Category has not been confirmed, so the listing does not state it.", correction: null },
    ],
    limits: "A readability and evidence check on your own text. It is not a marketplace review, not a compliance check and not a prediction of ranking, conversion or sales.",
  },
  ci: { used: true, considerIfTrue: ["insulated"], rows: [
    { theme: "reusable", sharedBy: { count: 2, of: 2 }, support: "SUPPORTED", insightIds: ["i1"], sources: ["keyword_themes"], limitation: "Derived words from your tracked competitors' saved listings. Not search demand." },
    { theme: "insulated", sharedBy: { count: 1, of: 2 }, support: "CONSIDER_IF_TRUE", insightIds: ["i1"], sources: ["differentiation_opportunities"], limitation: "Derived words." },
  ] },
  states: { generated: { done: true, at: "2026-10-30T10:00:00Z" }, audited: { done: true, at: "2026-10-30T10:00:01Z", verdict: "CHECKED_NOT_VERIFIED" }, approvedForUse: { done: false, at: null, meaning: "Approved for use in Metrion; not published." },
    copied: { count: 0, at: null }, markedUsed: { count: 0, at: null }, published: { known: false, note: "Metrion cannot see or change what is on a marketplace." } },
  editHint: "Change bullet 3 to: your own text", approveHint: "Approved for use in Metrion; not published.", ...over,
});

describe("the complete listing card", () => {
  it("is recognised only when it is a LISTING card with an audit", () => {
    expect(isListingCard(card())).toBe(true);
    expect(isListingCard({ kind: "LISTING" })).toBe(false);
    expect(isListingCard({ kind: "READINESS", audit: {} })).toBe(false);
    expect(isListingCard(null)).toBe(false);
  });

  it("shows the unverified-rules banner exactly, and no banner when the rules were verified", () => {
    const { rerender } = render(<ListingCard card={card()} onSend={() => {}} />);
    expect(screen.getByTestId("listing-banner")).toHaveTextContent(BANNER);
    expect(screen.getByRole("note")).toBeInTheDocument();
    rerender(<ListingCard card={card({ banner: null, rulesBasis: "VERIFIED" })} onSend={() => {}} />);
    expect(screen.queryByTestId("listing-banner")).toBeNull();
  });

  it("calls out a listing built from a previous title (N-15d) only when the backend says OUTDATED, and changes nothing else", () => {
    const status = (state: "CURRENT" | "OUTDATED" | "UNKNOWN") => ({
      state, reason: null, marketplace: "AMAZON", product: "AquaNest bottle", builtFrom: "Old title", currentApproved: state === "OUTDATED" ? "New title" : null,
      explanation: "This listing for AquaNest bottle on Amazon was built from a previous title.", nextStep: state === "OUTDATED" ? "Nothing was changed or regenerated. Ask me to write the complete listing again." : null,
    });
    const { rerender } = render(<ListingCard card={card({ titleStatus: status("OUTDATED") })} onSend={() => {}} />);
    const note = screen.getByTestId("listing-title-outdated");
    expect(note).toHaveTextContent("Built from a previous title · AquaNest bottle on Amazon");
    expect(note).toHaveTextContent("Old title");
    expect(note).toHaveTextContent("New title");
    expect(note).toHaveTextContent("Nothing was changed or regenerated");
    expect(screen.getByTestId("listing-banner")).toBeInTheDocument(); // the rules banner is separate and still shown
    for (const s of ["CURRENT", "UNKNOWN"] as const) {
      rerender(<ListingCard card={card({ titleStatus: status(s) })} onSend={() => {}} />);
      expect(screen.queryByTestId("listing-title-outdated")).toBeNull();
    }
    rerender(<ListingCard card={card()} onSend={() => {}} />); // an older card without the field
    expect(screen.queryByTestId("listing-title-outdated")).toBeNull();
  });

  it("keeps the states separate and never claims the listing is published, live or accepted", () => {
    render(<ListingCard card={card()} onSend={() => {}} />);
    const states = screen.getByTestId("listing-states");
    for (const w of ["Generated", "Audited", "Approved for use in Metrion", "Copied", "Marked as used", "Published on a marketplace: not tracked"]) expect(states).toHaveTextContent(w);
    expect(screen.getByTestId("state-approved")).toHaveTextContent("○ Approved for use in Metrion · not yet");
    expect(screen.getByTestId("state-published")).toHaveTextContent("Metrion cannot see or change what is on a marketplace");
    const whole = (document.body.textContent ?? "").replace(screen.getByTestId("listing-notice").textContent ?? "", "").replace(screen.getByTestId("state-published").textContent ?? "", ""); // the card's own denials are removed first: only an affirmative claim would remain
    expect(whole).not.toMatch(/(is|are|now|already|been) (published|live)/i);
    expect(whole).not.toMatch(/compliant|accepted by amazon|marketplace approved|\bREADY\b/);
  });

  it("shows the audit verdict and every one of the fifteen checks as a word with a mark, never a score", async () => {
    render(<ListingCard card={card()} onSend={() => {}} />);
    expect(screen.getByTestId("audit-verdict")).toHaveTextContent("CHECKED, NOT VERIFIED");
    expect(screen.getByTestId("audit-verdict")).toHaveTextContent("not checked against marketplace rules");
    await userEvent.click(screen.getByText("All 15 checks"));
    for (const id of IDS) expect(screen.getByTestId(`check-${id}`)).toBeInTheDocument();
    expect(screen.getByTestId("check-A13")).toHaveTextContent("? NOT ASSESSED");
    expect(screen.getByTestId("check-A12")).toHaveTextContent("– NOT APPLICABLE");
    expect(screen.getByTestId("check-A15")).toHaveTextContent("Spelling, grammar and writing style are not checked");
    expect(screen.getByTestId("check-A01")).toHaveTextContent("✓ PASS");
    expect(screen.getByTestId("listing-audit").textContent).not.toMatch(/\/\s?100|\bscore\b/i);
  });

  it("lists findings by severity with the section, the reason and the fix", () => {
    render(<ListingCard card={card()} onSend={() => {}} />);
    expect(within(screen.getByTestId("findings-warning")).getByText(/bullet 1/i)).toBeInTheDocument();
    expect(screen.getByTestId("findings-note")).toHaveTextContent("whole listing");
    expect(screen.getByTestId("findings-warning")).toHaveTextContent("not a marketplace or ranking rule");
    expect(screen.getByTestId("findings-warning")).toHaveTextContent("Fix: Say it once.");
    expect(screen.getByTestId("findings-note")).toHaveTextContent("Category has not been confirmed");
    expect(screen.queryByTestId("findings-blocker")).toBeNull();
  });

  it("shows where each researched keyword is used, why one is not, and that this is not demand or ranking", () => {
    render(<ListingCard card={card()} onSend={() => {}} />);
    const map = screen.getByTestId("keyword-map");
    expect(map).toHaveTextContent("steel bottle: title, bullet 1 ×2");
    expect(map).toHaveTextContent("gym: not used (not needed)");
    expect(map).toHaveTextContent("reusable: Not used: evidence is weak.");
    expect(map).toHaveTextContent("not search volume, ranking, buyer demand or conversion");
  });

  it("keeps supported competitor themes apart from 'consider adding if true', and never writes the second kind in", () => {
    render(<ListingCard card={card()} onSend={() => {}} />);
    expect(screen.getByTestId("ci-reusable")).toHaveTextContent("matches a detail you confirmed");
    expect(screen.getByTestId("ci-insulated")).toHaveTextContent("Consider adding if true for your product (not written into the listing)");
    expect(screen.getByTestId("listing-ci")).toHaveTextContent("Not search demand");
  });

  it("hides the competitor block when no competitor evidence exists", () => {
    render(<ListingCard card={card({ ci: { rows: [], considerIfTrue: [], used: false } })} onSend={() => {}} />);
    expect(screen.queryByTestId("listing-ci")).toBeNull();
  });

  it("copies one piece of text and tells the caller (best effort), without approving anything", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onCopied = vi.fn();
    const onApprove = vi.fn();
    render(<ListingCard card={card()} onSend={() => {}} onApprove={onApprove} onCopied={onCopied} />);
    await userEvent.click(screen.getByRole("button", { name: "Copy Bullet 2" }));
    expect(writeText).toHaveBeenCalledWith("Holds 1 litre");
    expect(onCopied).toHaveBeenCalledWith("gen-1");
    expect(onApprove).not.toHaveBeenCalled();
    expect(screen.getByTestId("state-approved")).toHaveTextContent("not yet");
  });

  it("approves for use only on a click, shows the exact wording, and says nothing was published", async () => {
    const onApprove = vi.fn().mockResolvedValue({ message: "Approved for use in Metrion; not published.", banner: BANNER });
    render(<ListingCard card={card()} onSend={() => {}} onApprove={onApprove} />);
    expect(screen.getByTestId("approve-note")).toHaveTextContent("It does not publish anything");
    await userEvent.click(screen.getByTestId("approve-for-use"));
    expect(onApprove).toHaveBeenCalledWith("gen-1");
    expect(await screen.findByText("✓ Approved for use")).toBeInTheDocument();
    expect(screen.getByTestId("approve-note")).toHaveTextContent("Approved for use in Metrion; not published.");
    expect(screen.getByTestId("approve-for-use")).toBeDisabled();
  });

  it("does not mark a failed approval as approved", async () => {
    render(<ListingCard card={card()} onSend={() => {}} onApprove={vi.fn().mockRejectedValue(new Error("x"))} />);
    await userEvent.click(screen.getByTestId("approve-for-use"));
    expect(await screen.findByText("I could not record that. Nothing was changed.")).toBeInTheDocument();
    expect(screen.getByTestId("state-approved")).toHaveTextContent("not yet");
    expect(screen.getByTestId("approve-for-use")).not.toBeDisabled();
  });

  it("cannot approve a blocked version and says why", () => {
    const blocked = card({ audit: { ...card().audit, verdict: "BLOCKED", counts: { blockers: 1, warnings: 0, notes: 0 }, findings: [{ check: "A04", severity: "BLOCKER", section: "BULLET 2", code: "UNSUPPORTED_CLAIM", explanation: "It says or implies “insulated”, which you have not confirmed.", correction: "Remove it." }] } });
    render(<ListingCard card={blocked} onSend={() => {}} onApprove={vi.fn()} />);
    expect(screen.getByTestId("approve-for-use")).toBeDisabled();
    expect(screen.getByTestId("approve-note")).toHaveTextContent("must be fixed first");
    expect(screen.getByTestId("audit-verdict")).toHaveTextContent("BLOCKED");
    expect(screen.getByTestId("findings-blocker")).toHaveTextContent("MUST FIX");
  });

  it("shows an already approved version as approved, not as pending", () => {
    render(<ListingCard card={card({ states: { ...card().states, approvedForUse: { done: true, at: "2026-10-30T11:00:00Z", meaning: "x" } } })} onSend={() => {}} onApprove={vi.fn()} />);
    expect(screen.getByTestId("state-approved")).toHaveTextContent("✓ Approved for use in Metrion");
    expect(screen.getByTestId("approve-for-use")).toBeDisabled();
  });

  it("sends the seller's edit as the fixed sentence, exactly as typed, and is disabled while the CEO is busy", async () => {
    const onSend = vi.fn();
    const { rerender } = render(<ListingCard card={card()} onSend={onSend} />);
    await userEvent.type(screen.getByLabelText("Change one section of the listing"), "Change bullet 3 to: Wide mouth for easy cleaning.");
    await userEvent.click(screen.getByRole("button", { name: "Send change" }));
    expect(onSend).toHaveBeenCalledWith("Change bullet 3 to: Wide mouth for easy cleaning.");
    rerender(<ListingCard card={card()} onSend={onSend} disabled />);
    expect(screen.getByLabelText("Change one section of the listing")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send change" })).toBeDisabled();
  });

  it("says when this is a revised version and omits backend terms that do not exist", () => {
    render(<ListingCard card={card({ revisionOf: "gen-0", marketplace: "FLIPKART", sections: { ...card().sections, backend_terms: null } })} onSend={() => {}} />);
    expect(screen.getByText("This is a revised version. The earlier version is still saved.")).toBeInTheDocument();
    expect(screen.queryByTestId("section-backend-terms")).toBeNull();
    expect(screen.getByLabelText("Your complete listing")).toHaveTextContent("Flipkart");
  });
});
