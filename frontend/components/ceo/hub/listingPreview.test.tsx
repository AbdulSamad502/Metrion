import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ListingPreviewCard } from "@/components/ceo/hub/ListingPreviewCard";
import type { PreviewCard, PreviewMarketplace, PreviewOption, PreviewScreen } from "@/lib/ceo";

const LONG = "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use at Home, Gym and Office";
const screen_ = (text: string, limit: number, basis: "ILLUSTRATIVE" | "VERIFIED" = "ILLUSTRATIVE"): PreviewScreen => {
  const cut = text.length > limit;
  const visible = cut ? text.slice(0, text.lastIndexOf(" ", limit)).replace(/[ ,]+$/, "") : text;
  return {
    visible, hidden: cut ? text.slice(visible.length).trim() : "", truncated: cut, visibleChars: visible.length, totalChars: text.length, limit, limitBasis: basis,
    limitNote: basis === "VERIFIED" ? "From the display rule checked 2026-10-01." : "Illustrative cut-off for demonstration. It is not an official limit.",
    keywords: [{ keyword: "stainless steel water bottle", status: "VISIBLE" }, { keyword: "gym water bottle", status: cut ? "CUT_OFF" : "VISIBLE" }, { keyword: "garden hose", status: "NOT_IN_TITLE" }],
    details: [{ label: "Brand", value: "AquaNest", status: "VISIBLE" }, { label: "Color", value: "silver", status: "VISIBLE" }, { label: "Weight", value: "500 g", status: "NOT_IN_TITLE" }],
    suggestions: cut ? [`Your gym would be hidden on ${limit === 60 ? "mobile" : "desktop"}. Move it earlier or shorten the title.`] : ["The whole title fits in this illustrative desktop view."],
  };
};
const option = (rank: number, text: string, over: Partial<PreviewOption> = {}): PreviewOption => ({
  optionId: `o${rank}`, rank, text, strategy: "Brand-first", hardFailures: [],
  score: { status: "ASSESSED", score: 90 - rank * 4, band: "strong", assessablePoints: 100, note: "n", criteria: {} },
  compliance: { status: "NOT_ASSESSED", detail: "Not assessed: no verified marketplace rule is available." },
  modes: { mobile: screen_(text, 60), desktop: screen_(text, 110) }, ...over,
});
const set = (marketplace: PreviewMarketplace, texts: string[]) => ({ marketplace, generationId: "g-" + marketplace, analysisId: "a", recommendedOptionId: "o1", recommendation: "Option 1 has the highest internal quality score (86/100, 100 of 100 points assessable).",
  options: texts.map((t, i) => option(i + 1, t, i === 2 ? { hardFailures: ["Says something you have not confirmed: it claims “insulated”."], score: { status: "ASSESSED", score: 67, band: "NOT_USABLE", assessablePoints: 100, criteria: {} } } : i === 3 ? { score: { status: "NOT_ASSESSED", note: "Not enough evidence for an overall score.", assessablePoints: 35, criteria: {} } } : {})) });
const TITLES = [LONG, "AquaNest Stainless Steel Water Bottle 1L, Silver", "AquaNest Insulated Stainless Steel Water Bottle 1 Litre", "Water Bottle", "AquaNest Steel Bottle"];
const card = (over: Partial<PreviewCard> = {}): PreviewCard => ({
  version: 1, kind: "PREVIEW", method: "listing-preview-v1", notice: "This is an illustrative simulation of a search result, not the real marketplace page. Price, rating and reviews are not simulated. The real display may cut the title at a different point.",
  investigationId: "inv-1", product: { name: "AquaNest 1 Litre Stainless Steel Water Bottle", brand: "AquaNest" }, image: null,
  imageNote: "No product photo was attached for this product in this conversation, so a neutral placeholder is shown. Metrion never generates a product picture.",
  marketplaces: ["AMAZON", "FLIPKART"], missingMarketplaces: ["MEESHO"], sets: [set("AMAZON", TITLES), set("FLIPKART", TITLES.slice().reverse())], defaultMode: "mobile",
  limits: ["The score is an internal listing-quality assessment, not a marketplace ranking, search position, conversion rate or sales prediction."], ...over,
});

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
});
afterEach(() => vi.unstubAllGlobals());

describe("the visual listing preview card", () => {
  it("shows an actual simulated search-result card, clearly marked as an illustrative simulation", () => {
    render(<ListingPreviewCard card={card()} />);
    expect(screen.getByTestId("listing-preview")).toBeInTheDocument();
    expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-marketplace", "AMAZON");
    expect(screen.getByTestId("preview-notice")).toHaveTextContent("illustrative simulation of a search result, not the real marketplace page");
    expect(screen.getAllByText("ILLUSTRATIVE SIMULATION").length).toBeGreaterThan(0);
    expect(screen.getByTestId("preview-visible")).toHaveTextContent("AquaNest 1 Litre Stainless Steel Water Bottle");
  });

  it("switches between mobile and desktop instantly, with no request", async () => {
    render(<ListingPreviewCard card={card()} />);
    expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-mode", "mobile");
    expect(screen.getByTestId("preview-hidden")).toBeInTheDocument(); // the long title is cut on a phone
    const mobileVisible = screen.getByTestId("preview-visible").textContent ?? "";
    await userEvent.click(screen.getByRole("button", { name: "Desktop" }));
    expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-mode", "desktop");
    expect((screen.getByTestId("preview-visible").textContent ?? "").length).toBeGreaterThan(mobileVisible.length);
    expect(screen.getByRole("button", { name: "Desktop" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Mobile" }));
    expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-mode", "mobile");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("switches between the three marketplaces that have titles and disables the one that has none", async () => {
    render(<ListingPreviewCard card={card()} />);
    const meesho = screen.getByRole("tab", { name: /Meesho/ });
    expect(meesho).toBeDisabled();
    expect(meesho).toHaveTextContent("no titles yet");
    await userEvent.click(screen.getByRole("tab", { name: "Flipkart" }));
    expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-marketplace", "FLIPKART");
    expect(screen.getByTestId("preview-stage")).toHaveTextContent("Flipkart-style layout");
    await userEvent.click(screen.getByRole("tab", { name: "Amazon" }));
    expect(screen.getByTestId("preview-stage")).toHaveTextContent("Amazon-style layout");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("supports all three marketplaces when all have titles", async () => {
    const c = card({ marketplaces: ["AMAZON", "FLIPKART", "MEESHO"], missingMarketplaces: [], sets: [set("AMAZON", TITLES), set("FLIPKART", TITLES), set("MEESHO", TITLES)] });
    render(<ListingPreviewCard card={c} />);
    await userEvent.click(screen.getByRole("tab", { name: "Meesho" }));
    expect(screen.getByTestId("preview-stage")).toHaveTextContent("Meesho-style layout");
  });

  it("previews each of the five saved titles with its score, assessable points and marketplace-rule status", async () => {
    render(<ListingPreviewCard card={card()} />);
    const tabs = within(screen.getByRole("tablist", { name: "Title options" })).getAllByRole("tab");
    expect(tabs).toHaveLength(5);
    expect(screen.getByTestId("preview-score-line")).toHaveTextContent("86/100 (strong) · 100 of 100 points assessable"); // option 1 is shown first (the recommended one)
    expect(screen.getByTestId("preview-compliance")).toHaveTextContent("NOT ASSESSED");
    await userEvent.click(tabs[1]);
    expect(screen.getByTestId("preview-visible")).toHaveTextContent("AquaNest Stainless Steel Water Bottle 1L, Silver");
    expect(screen.getByTestId("preview-score-line")).toHaveTextContent("82/100");
    await userEvent.click(tabs[3]);
    expect(screen.getByTestId("preview-score-line")).toHaveTextContent("No overall score");
  });

  it("states a hard failure in words, never only in colour", async () => {
    render(<ListingPreviewCard card={card()} />);
    await userEvent.click(screen.getByRole("tab", { name: /Option 3 · HARD FAIL/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("HARD FAIL: never recommended whatever its score");
    expect(screen.getByTestId("preview-compliance")).toHaveTextContent(/NOT ASSESSED|PASS|FAIL/);
  });

  it("shows a PASS or FAIL rule status as a word with a mark, separate from the score", async () => {
    const c = card();
    c.sets[0].options[0].compliance = { status: "PASS", detail: "Within the verified marketplace rule (112 of 200 characters)." };
    c.sets[0].options[1].compliance = { status: "FAIL", detail: "Breaks the verified marketplace rule: too long." };
    render(<ListingPreviewCard card={c} />);
    expect(screen.getByTestId("preview-compliance")).toHaveTextContent("✓ PASS");
    await userEvent.click(screen.getByRole("tab", { name: /Option 2/ }));
    expect(screen.getByTestId("preview-compliance")).toHaveTextContent("✗ FAIL");
  });

  it("highlights what is visible and hidden, keyword visibility, details and suggestions", () => {
    render(<ListingPreviewCard card={card()} />);
    expect(screen.getByTestId("preview-hidden")).toHaveTextContent("Hidden:");
    expect(screen.getByTestId("preview-keywords")).toHaveTextContent("gym water bottle: cut off");
    expect(screen.getByTestId("preview-keywords")).toHaveTextContent("garden hose: not in this title");
    expect(screen.getByTestId("preview-details")).toHaveTextContent("Brand (AquaNest): visible");
    expect(screen.getByTestId("preview-details")).toHaveTextContent("Weight (500 g): not in this title");
    expect(screen.getByTestId("preview-suggestions")).toHaveTextContent("would be hidden on mobile");
    expect(screen.getByTestId("preview-truncation")).toHaveTextContent("ILLUSTRATIVE (not an official limit)");
  });

  it("labels a verified display rule as verified and an illustrative one as not official", async () => {
    const c = card();
    c.sets[0].options[0].modes.desktop = screen_(LONG, 110, "VERIFIED");
    render(<ListingPreviewCard card={c} />);
    expect(screen.getByTestId("preview-truncation")).toHaveTextContent("ILLUSTRATIVE");
    await userEvent.click(screen.getByRole("button", { name: "Desktop" }));
    expect(screen.getByTestId("preview-truncation")).toHaveTextContent("VERIFIED display rule");
  });

  it("shows a neutral placeholder when there is no photo and never invents one", () => {
    render(<ListingPreviewCard card={card()} />);
    expect(screen.getByTestId("preview-image-placeholder")).toBeInTheDocument();
    expect(screen.queryByTestId("preview-image")).toBeNull();
    expect(screen.getByText(/Metrion never generates a product picture/)).toBeInTheDocument();
  });

  it("shows the seller's own photo when there is one", async () => {
    const loadImage = vi.fn(async () => "blob:photo");
    render(<ListingPreviewCard card={card({ image: { attachmentId: "att-1", filename: "shelf.jpg" }, imageNote: "Your photo “shelf.jpg” from this conversation." })} loadImage={loadImage} />);
    const img = await screen.findByTestId("preview-image");
    expect(img).toHaveAttribute("src", "blob:photo");
    expect(img).toHaveAttribute("alt", "Your product photo shelf.jpg");
    expect(loadImage).toHaveBeenCalledWith("inv-1", "att-1");
    await userEvent.click(screen.getByRole("button", { name: "Desktop" }));
    expect(loadImage).toHaveBeenCalledTimes(1); // switching screens does not fetch it again
  });

  it("falls back to the placeholder when the photo cannot be loaded", async () => {
    render(<ListingPreviewCard card={card({ image: { attachmentId: "att-1", filename: "x.jpg" } })} loadImage={async () => { throw new Error("nope"); }} />);
    expect(await screen.findByTestId("preview-image-placeholder")).toBeInTheDocument();
  });

  it("shows the placeholder, and fetches nothing, when no loader is given", () => {
    render(<ListingPreviewCard card={card({ image: { attachmentId: "att-1", filename: "x.jpg" } })} />);
    expect(screen.getByTestId("preview-image-placeholder")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("simulates no price, rating, review or sales figure", () => {
    render(<ListingPreviewCard card={card()} />);
    const text = screen.getByTestId("preview-stage").textContent ?? "";
    expect(text).not.toMatch(/₹|\bRs\b|★|stars|reviews? \(|\d+ sold|bestseller|% off/i);
    expect(text).toContain("Price, rating and reviews are not simulated.");
  });

  it("escapes the title text and never renders it as HTML", () => {
    const c = card();
    c.sets[0].options[0].modes.mobile.visible = "<img src=x onerror=alert(1)> Steel Bottle";
    const { container } = render(<ListingPreviewCard card={c} />);
    expect(container.querySelector("img[src='x']")).toBeNull();
    expect(screen.getByTestId("preview-visible")).toHaveTextContent("<img src=x onerror=alert(1)> Steel Bottle");
  });

  it("shows nothing when the card has no titles", () => {
    const { container } = render(<ListingPreviewCard card={card({ sets: [], marketplaces: [] })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
