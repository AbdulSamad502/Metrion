import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import type { CeoMessage, PreviewCard, PreviewOption, PreviewScreen } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
beforeEach(() => { fake = new FakeCeo(); });

const TITLE = "AquaNest 1 Litre Stainless Steel Water Bottle, Silver, Reusable Bottle for Daily Use at Home, Gym and Office";
const screenFor = (limit: number): PreviewScreen => {
  const cut = TITLE.length > limit;
  const visible = cut ? TITLE.slice(0, TITLE.lastIndexOf(" ", limit)).replace(/[ ,]+$/, "") : TITLE;
  return { visible, hidden: cut ? TITLE.slice(visible.length).trim() : "", truncated: cut, visibleChars: visible.length, totalChars: TITLE.length, limit, limitBasis: "ILLUSTRATIVE", limitNote: "Illustrative cut-off for demonstration. It is not an official limit.",
    keywords: [{ keyword: "stainless steel water bottle", status: "VISIBLE" }], details: [{ label: "Brand", value: "AquaNest", status: "VISIBLE" }], suggestions: ["The whole title fits in this illustrative desktop view."] };
};
const option: PreviewOption = { optionId: "o1", rank: 1, text: TITLE, strategy: "Brand-first", hardFailures: [], score: { status: "ASSESSED", score: 100, band: "strong", assessablePoints: 100, criteria: {} },
  compliance: { status: "NOT_ASSESSED", detail: "Not assessed: no verified marketplace rule is available." }, modes: { mobile: screenFor(60), desktop: screenFor(110) } };
const card: PreviewCard = { version: 1, kind: "PREVIEW", method: "listing-preview-v1", notice: "This is an illustrative simulation of a search result, not the real marketplace page.", investigationId: "inv-1",
  product: { name: "AquaNest 1 Litre Stainless Steel Water Bottle", brand: "AquaNest" }, image: null, imageNote: "No product photo was attached for this product in this conversation, so a neutral placeholder is shown. Metrion never generates a product picture.",
  marketplaces: ["AMAZON"], missingMarketplaces: ["FLIPKART", "MEESHO"], sets: [{ marketplace: "AMAZON", generationId: "g", analysisId: "a", recommendedOptionId: "o1", recommendation: "Option 1 has the highest internal quality score.", options: [option] }],
  defaultMode: "mobile", limits: ["The score is an internal listing-quality assessment."] };
const messages: CeoMessage[] = [
  { id: "m1", role: "USER", kind: "TEXT", content: "Show my listing preview", turn_id: "t1", created_at: "2026-10-30T10:00:00.000Z" },
  { id: "m2", role: "CEO", kind: "ANSWER", content: "Here is your listing preview. It is an illustrative simulation of a search result, not the real marketplace page.", turn_id: "t1", created_at: "2026-10-30T10:00:01.000Z", choices: card },
];
const turn = { id: "t1", route: "ADVISORY", route_key: null, status: "DELIVERED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-30T10:00:00.000Z" };

describe("CEO Hub: the listing preview in the chat", () => {
  it("shows the actual visual card inside the conversation and lets the seller switch screens in place", async () => {
    const id = fake.seed({ id: "inv-1", messages: structuredClone(messages), turns: [turn] as never });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("open-drawer"));
    await u.click(await screen.findByTestId(`investigation-${id}`));
    const conversation = await screen.findByTestId("conversation");
    const preview = within(conversation).getByTestId("listing-preview");
    expect(within(preview).getByTestId("preview-stage")).toHaveAttribute("data-mode", "mobile");
    await u.click(within(preview).getByRole("button", { name: "Desktop" }));
    expect(within(preview).getByTestId("preview-stage")).toHaveAttribute("data-mode", "desktop");
    expect(within(conversation).queryByTestId("pick-card")).toBeNull();
    expect(within(conversation).queryByText(/Choose an option|decision/i)).toBeNull(); // it is a picture of a result, not a question waiting for an answer
  });

  it("keeps the card in the thread when a later message follows it", async () => {
    const later: CeoMessage = { id: "m3", role: "CEO", kind: "ANSWER", content: "Anything else?", turn_id: "t1", created_at: "2026-10-30T10:00:02.000Z" };
    const id = fake.seed({ id: "inv-1", messages: structuredClone([...messages, later]), turns: [turn] as never });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("open-drawer"));
    await u.click(await screen.findByTestId(`investigation-${id}`));
    expect(within(await screen.findByTestId("conversation")).getByTestId("listing-preview")).toBeInTheDocument();
  });
});
