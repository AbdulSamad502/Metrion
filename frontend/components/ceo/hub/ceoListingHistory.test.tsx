import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import type { CeoMessage, HistoryCompare, HistoryList, HistoryVersion } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
beforeEach(() => { fake = new FakeCeo(); });

const ver = (n: number): HistoryVersion => ({
  id: `v${n}`, number: n, sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", title: "AquaNest Steel Bottle", createdAt: `2026-10-0${n}T09:00:00Z`, source: n === 1 ? "ORIGINAL" : "SELLER_EDIT",
  sourceText: n === 1 ? "Original listing written by Metrion" : "Your own edit: bullet 2", changedSection: null, parentId: n === 1 ? null : `v${n - 1}`, parentNumber: n === 1 ? null : n - 1, originalNumber: 1, lineageIssue: null,
  isLatest: n === 2, states: { approvedForUse: { done: false, at: null }, audited: { done: true, verdict: "NEEDS_ATTENTION", at: null, records: 1 }, copied: 0, markedUsed: 0, published: { known: false } },
});
const list: HistoryList = {
  kind: "LISTING_HISTORY", view: "HISTORY", filters: { sku: null, marketplace: null }, total: 2, limit: 20, offset: 0, hasMore: false, versions: [ver(2), ver(1)], empty: false,
  groups: [{ sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", versionCount: 2, latestNumber: 2, latestId: "v2" }], notice: "Approved for use means you approved that version inside Metrion.", published: "Metrion cannot see or change what is on a marketplace.",
};
const term = { available: true, reason: null, added: [], removed: [], retained: [], changed: false };
const compare: HistoryCompare = {
  kind: "LISTING_HISTORY", view: "COMPARE", sku: "aquanest", marketplace: "AMAZON", product: "AquaNest bottle", swapped: false, identical: false,
  older: { id: "v1", number: 1, createdAt: "2026-10-01T09:00:00Z", sourceText: "Original listing written by Metrion", approved: false }, newer: { id: "v2", number: 2, createdAt: "2026-10-02T09:00:00Z", sourceText: "Your own edit: bullet 2", approved: false },
  sectionsChanged: { bullets: true }, title: { changed: false, ops: [], addedWords: [], removedWords: [], old: "", new: "", oldLength: { characters: 0, words: 0 }, newLength: { characters: 0, words: 0 }, characterDelta: 0, attributes: { removed: [], introduced: [] } },
  bullets: { changed: true, counts: { unchanged: 2, added: 1 }, items: [{ status: "added", old: null, new: "Holds 1 litre of water", oldPosition: null, newPosition: 2 }] }, description: { changed: false, counts: {}, items: [] },
  keywords: term, backendTerms: term, hashtags: term, keywordMovement: { rows: [], counts: { ADDED: 0, REMOVED: 0, MOVED: 0, RETAINED: 0 }, limits: "Search volume, ranking and demand are not assessed." },
  audit: { available: true, reason: null, olderVerdict: "NEEDS_ATTENTION", newerVerdict: "NEEDS_ATTENTION", new: [], resolved: [], unresolved: [] }, claims: { available: true, reason: null, new: [] },
  attributes: { available: true, removed: [], introduced: [] }, performance: { state: "NOT_ASSESSED", never: "Sales, revenue, conversion, search ranking, visibility and demand are not assessed for a listing revision.", missing: "No comparable marketplace performance data is available.", note: "n" },
  notice: "These are differences in the saved text.", published: "p",
};
const messages: CeoMessage[] = [
  { id: "m1", role: "USER", kind: "TEXT", content: "Show my listing history", turn_id: "t1", created_at: "2026-10-31T10:00:00.000Z" },
  { id: "m2", role: "CEO", kind: "ANSWER", content: "AquaNest bottle on Amazon: 2 versions, latest is version 2.", turn_id: "t1", created_at: "2026-10-31T10:00:01.000Z", choices: list },
];
const turn = { id: "t1", route: "ADVISORY", route_key: null, status: "DELIVERED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-31T10:00:00.000Z" };

async function open() {
  const id = fake.seed({ id: "inv-1", messages: structuredClone(messages), turns: [turn] as never });
  render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
  const u = userEvent.setup();
  await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  return { u, conversation: await screen.findByTestId("conversation") };
}

describe("CEO Hub: the listing history in the chat (CMO 3.0 M7)", () => {
  it("shows the history card in the conversation and not a decision card, and compares two versions through the client", async () => {
    fake.history.list = list;
    fake.history.compare = compare;
    const { u, conversation } = await open();
    const card = within(conversation).getByTestId("listing-history");
    expect(within(card).getAllByTestId("history-version")).toHaveLength(2);
    expect(within(conversation).queryByText(/Choose an option|decision/i)).toBeNull();
    await u.click(within(card).getByLabelText("Select version 1 to compare"));
    await u.click(within(card).getByLabelText("Select version 2 to compare"));
    await u.click(within(card).getByTestId("compare-selected"));
    expect(await within(conversation).findByTestId("history-compare")).toBeInTheDocument();
    expect(fake.calls.some((c) => c.method === "compare" && c.args[0] === "v1" && c.args[1] === "v2")).toBe(true);
    expect(within(conversation).getByTestId("performance-state")).toHaveTextContent("Not assessed");
  });

  it("shows a plain error with a way to retry when the server fails, and keeps the history readable", async () => {
    fake.history.list = list;
    fake.history.error = new ApiError(500, "boom");
    const { u, conversation } = await open();
    await u.click(within(conversation).getByRole("button", { name: "Open version 2" }));
    expect(await within(conversation).findByTestId("history-error")).toHaveTextContent("I could not load that just now");
    expect(within(conversation).getAllByTestId("history-version")).toHaveLength(2);
  });
});
