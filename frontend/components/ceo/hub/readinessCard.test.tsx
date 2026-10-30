import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ReadinessCard } from "@/components/ceo/hub/ReadinessCard";
import type { BuyerQuestion, CeoMessage, MarketReadiness, ReadinessCard as Card, ReadinessItem } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

const q = (id: string, topic: string, over: Partial<BuyerQuestion> = {}): BuyerQuestion => ({
  id, topic, question: `Question about ${topic}?`, importance: "ESSENTIAL", claim: false, status: "NOT_CONFIRMED", answer: null, source: null, ask: `Tell me about its ${topic.toLowerCase()}.`,
  listingUse: "Not stated in your listing until you confirm it.", evidence: [], ...over,
});
const QUESTIONS: BuyerQuestion[] = [
  q("material", "Material", { status: "CONFIRMED", answer: "stainless steel", source: { label: "Material", origin: "you told me", at: "2026-10-28" }, ask: null, listingUse: "Can be used in your listing exactly as you stated it." }),
  q("insulated", "Insulated", { claim: true, importance: "COMPETITOR_RELEVANT", listingUse: "Must NOT be claimed in your listing until you confirm it." }),
  q("dishwasher", "Dishwasher safe", { claim: true, status: "SELLER_UNKNOWN", ask: "You told me this is not confirmed (“unknown”). I will not claim it unless you tell me otherwise." }),
];
const item = (id: string, label: string, status: ReadinessItem["status"], max: number, earned: number | null, detail: string, action: string | null = null): ReadinessItem => ({ id, label, status, max, earned, detail, action });
const market = (marketplace: "AMAZON" | "FLIPKART" | "MEESHO", over: Partial<MarketReadiness> = {}): MarketReadiness => ({
  marketplace, verdict: "NOT_READY", verdictText: "Not ready: some requirements are still missing.",
  score: { status: "ASSESSED", score: 61, earnedPoints: 58, assessablePoints: 95, note: "Based on 95 of 100 assessable points; requirements that could not be assessed are left out, not counted as passed or as zero." },
  counts: { done: 6, missing: 4, blocked: 0, notAssessed: 2 },
  nextActions: [{ id: "fact_size", label: "Size or capacity", action: "Tell me the size or capacity.", status: "MISSING", points: 5 }],
  categories: [
    { id: "facts", label: "Confirmed product facts", max: 25, status: "ASSESSED", earned: 15, assessable: 25, score: 60, items: [item("fact_brand", "Brand", "DONE", 5, 5, "You told me: AquaNest."), item("fact_size", "Size or capacity", "MISSING", 5, 0, "Not confirmed yet.", "Tell me the size or capacity.")] },
    { id: "marketplace", label: "Marketplace requirements", max: 5, status: "NOT_ASSESSED", earned: null, assessable: 0, score: null, items: [item("market_title_rule", `Title meets ${marketplace}'s verified length rule`, "NOT_ASSESSED", 5, null, "Not assessed: no verified, current rule exists, so this cannot be called met.")] },
  ], ...over,
});
const card = (over: Partial<Card> = {}): Card => ({
  version: 1, kind: "READINESS", view: "questions", notice: "This is an internal assessment, not a marketplace approval.", investigationId: "inv-1", product: { name: "AquaNest bottle", sku: "aquanest-bottle" }, defaultMarketplace: "AMAZON",
  questions: { counts: { CONFIRMED: 1, NOT_CONFIRMED: 1, SELLER_UNKNOWN: 1 }, questions: QUESTIONS, limits: ["Not drawn from search, review or marketplace Q&A data."] },
  readiness: { marketplaces: [market("AMAZON"), market("FLIPKART", { verdict: "BLOCKED", verdictText: "Blocked: something must be fixed before you list.", counts: { done: 3, missing: 6, blocked: 1, notAssessed: 2 } }),
                              market("MEESHO", { score: { status: "NOT_ASSESSED", assessablePoints: 30, note: "Not enough evidence for a readiness score: only 30 of 100 points could be assessed (at least 50 are needed)." } })], limits: ["It is never counted as passed."] },
  ...over,
});

describe("the buyer questions and readiness card", () => {
  it("shows each question with the seller's own answer and its source, or NOT CONFIRMED", () => {
    render(<ReadinessCard card={card()} onSend={() => {}} />);
    expect(screen.getByTestId("questions-summary")).toHaveTextContent("1 of 3 answered from your facts · 1 NOT CONFIRMED · 1 you said not confirmed");
    expect(screen.getByTestId("question-material")).toHaveTextContent("You told me: “stainless steel”");
    expect(screen.getByTestId("question-material")).toHaveTextContent("you told me, 2026-10-28; not checked by Metrion");
    expect(screen.getByTestId("question-insulated")).toHaveTextContent("? NOT CONFIRMED");
    expect(screen.getByTestId("question-insulated")).toHaveTextContent("Must NOT be claimed in your listing until you confirm it");
    expect(screen.getByTestId("question-insulated")).toHaveTextContent("Tell me about its insulated");
    expect(screen.getByTestId("question-dishwasher")).toHaveTextContent("○ You said it is not confirmed");
  });

  it("offers an answer box only for questions that are still open", () => {
    render(<ReadinessCard card={card()} onSend={() => {}} />);
    expect(within(screen.getByTestId("question-material")).queryByRole("textbox")).toBeNull();
    expect(within(screen.getByTestId("question-insulated")).getByRole("textbox", { name: /Your answer about insulated/ })).toBeInTheDocument();
  });

  it("sends the seller's answer as the one fixed sentence, exactly as if typed, and clears the box", async () => {
    const onSend = vi.fn();
    render(<ReadinessCard card={card()} onSend={onSend} />);
    const box = within(screen.getByTestId("question-dishwasher")).getByRole("textbox");
    const save = within(screen.getByTestId("question-dishwasher")).getByRole("button", { name: "Save answer" });
    expect(save).toBeDisabled();
    await userEvent.type(box, "yes, top rack, tested by me");
    await userEvent.click(save);
    expect(onSend).toHaveBeenCalledWith("For my AquaNest bottle, dishwasher safe is: yes, top rack, tested by me");
    expect(box).toHaveValue("");
  });

  it("does not send while the chat is busy", async () => {
    const onSend = vi.fn();
    render(<ReadinessCard card={card()} onSend={onSend} disabled />);
    expect(within(screen.getByTestId("question-insulated")).getByRole("textbox")).toBeDisabled();
    expect(within(screen.getByTestId("question-insulated")).getByRole("button", { name: "Save answer" })).toBeDisabled();
  });

  it("switches to readiness and between the three marketplaces without any request", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<ReadinessCard card={card()} onSend={() => {}} />);
    await userEvent.click(screen.getByRole("tab", { name: "Listing readiness" }));
    expect(screen.getByTestId("readiness-market")).toHaveAttribute("data-marketplace", "AMAZON");
    expect(screen.getByTestId("readiness-score")).toHaveTextContent("61/100 · 95 of 100 points assessable");
    expect(screen.getByTestId("readiness-verdict")).toHaveTextContent("NOT READY.");
    await userEvent.click(screen.getByRole("tab", { name: "Flipkart" }));
    expect(screen.getByTestId("readiness-verdict")).toHaveTextContent("BLOCKED.");
    await userEvent.click(screen.getByRole("tab", { name: "Meesho" }));
    expect(screen.getByTestId("readiness-score")).toHaveTextContent("No readiness score");
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows every requirement with its status as a word, its points, and never treats unknown as passed", async () => {
    render(<ReadinessCard card={card({ view: "readiness" })} onSend={() => {}} />);
    expect(screen.getByTestId("item-fact_brand")).toHaveTextContent("✓ DONE Brand (5/5)");
    expect(screen.getByTestId("item-fact_size")).toHaveTextContent("○ MISSING Size or capacity (0/5)");
    expect(screen.getByTestId("item-fact_size")).toHaveTextContent("Next: Tell me the size or capacity.");
    const rule = screen.getByTestId("item-market_title_rule");
    expect(rule).toHaveTextContent("? NOT ASSESSED");
    expect(rule).not.toHaveTextContent("DONE");
    expect(rule).not.toHaveTextContent("(0/5)"); // not assessed is never shown as zero points
    expect(screen.getByTestId("category-marketplace")).toHaveTextContent("not assessed");
    expect(screen.getByTestId("readiness-actions")).toHaveTextContent("Tell me the size or capacity.");
  });

  it("states the verdict in words and the limits, and says it is not a marketplace approval", () => {
    render(<ReadinessCard card={card({ view: "readiness" })} onSend={() => {}} />);
    expect(screen.getByTestId("readiness-notice")).toHaveTextContent("not a marketplace approval");
    expect(screen.getByText("It is never counted as passed.")).toBeInTheDocument();
  });

  it("opens on the view the seller asked for", () => {
    render(<ReadinessCard card={card({ view: "readiness" })} onSend={() => {}} />);
    expect(screen.getByRole("tab", { name: "Listing readiness" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("questions-summary")).toBeNull();
  });

  it("renders text as text, never as HTML", () => {
    const evil = card();
    evil.questions.questions[0].answer = "<img src=x onerror=alert(1)>";
    const { container } = render(<ReadinessCard card={evil} onSend={() => {}} />);
    expect(container.querySelector("img[src='x']")).toBeNull();
    expect(screen.getByTestId("question-material")).toHaveTextContent("<img src=x onerror=alert(1)>");
  });
});

let fake: FakeCeo;
beforeEach(() => { fake = new FakeCeo(); });

describe("CEO Hub: the readiness card in the chat", () => {
  it("shows the card inside the conversation and sends the seller's answer as a normal message", async () => {
    const messages: CeoMessage[] = [
      { id: "m1", role: "USER", kind: "TEXT", content: "What questions will buyers ask?", turn_id: "t1", created_at: "2026-10-30T10:00:00.000Z" },
      { id: "m2", role: "CEO", kind: "ANSWER", content: "Here are the questions buyers commonly ask about this kind of product.", turn_id: "t1", created_at: "2026-10-30T10:00:01.000Z", choices: card() },
    ];
    const turn = { id: "t1", route: "ADVISORY", route_key: null, status: "DELIVERED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-30T10:00:00.000Z" };
    const id = fake.seed({ id: "inv-1", messages: structuredClone(messages), turns: [turn] as never });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("open-drawer"));
    await u.click(await screen.findByTestId(`investigation-${id}`));
    const conversation = await screen.findByTestId("conversation");
    const c = within(conversation).getByTestId("readiness-card");
    await u.type(within(within(c).getByTestId("question-insulated")).getByRole("textbox"), "tested, keeps cold 12 hours");
    await u.click(within(within(c).getByTestId("question-insulated")).getByRole("button", { name: "Save answer" }));
    const sent = fake.calls.find((x) => x.method === "postTurn");
    expect(sent?.args[1]).toBe("For my AquaNest bottle, insulated is: tested, keeps cold 12 hours");
  });
});
