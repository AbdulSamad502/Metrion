import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ListingHistoryCard } from "@/components/ceo/hub/ListingHistoryCard";
import { ApiError } from "@/lib/api";
import { isHistoryCard } from "@/lib/ceo";
import type { HistoryApi, HistoryCompare, HistoryList, HistoryRecommendations, HistoryVersion, HistoryVersionDetail } from "@/lib/ceo";

const states = (approved = false) => ({ approvedForUse: { done: approved, at: approved ? "2026-10-02T00:00:00Z" : null }, audited: { done: true, verdict: "NEEDS_ATTENTION", at: "2026-10-01T00:00:00Z", records: 1 }, copied: 0, markedUsed: 0, published: { known: false as const } });
const ver = (n: number, over: Partial<HistoryVersion> = {}): HistoryVersion => ({
  id: `v${n}`, number: n, sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", title: "AquaNest Steel Water Bottle 1 Litre", createdAt: `2026-10-0${n}T09:00:00Z`, source: n === 1 ? "ORIGINAL" : "SELLER_EDIT",
  sourceText: n === 1 ? "Original listing written by Metrion" : "Your own edit: bullet 2", changedSection: n === 1 ? null : "BULLET 2", parentId: n === 1 ? null : `v${n - 1}`, parentNumber: n === 1 ? null : n - 1, originalNumber: 1,
  lineageIssue: null, isLatest: n === 3, states: states(n === 2), ...over,
});
const list = (versions = [ver(3), ver(2), ver(1)], over: Partial<HistoryList> = {}): HistoryList => ({
  kind: "LISTING_HISTORY", view: "HISTORY", filters: { sku: null, marketplace: null }, total: versions.length, limit: 20, offset: 0, hasMore: false, versions,
  groups: [{ sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", versionCount: versions.length, latestNumber: versions.length, latestId: "v3" }], empty: versions.length === 0,
  notice: "Approved for use means you approved that version inside Metrion. It does not mean it is published, live or accepted by a marketplace.", published: "Metrion cannot see or change what is on a marketplace, so it does not know which version, if any, is live.", ...over,
});
const detail: HistoryVersionDetail = {
  kind: "LISTING_HISTORY", view: "VERSION", version: ver(2), sections: { title: "AquaNest Steel Water Bottle 1 Litre", bullets: ["Holds 1 litre", "Reusable body"], description: "A bottle.", keywords: ["steel bottle"], backend_terms: ["flask"], hashtags: null },
  audit: { verdict: "NEEDS_ATTENTION", rulesBasis: "UNVERIFIED", createdAt: "2026-10-01T00:00:00Z", checks: [], findings: [{ check: "A08", severity: "WARNING", section: "BULLETS", code: "W2", explanation: "“steel” repeats.", correction: null }] },
  parent: { id: "v1", number: 1, createdAt: "2026-10-01T09:00:00Z" }, versionCount: 3, original: { id: "v1", number: 1 }, whyRevised: { recorded: "Your own edit: bullet 2", section: "BULLET 2", reasonRecorded: false, note: "Metrion records how and where a version changed, not your reason for changing it." },
  notice: "n", published: "p",
};
const term = { available: true, reason: null, added: [], removed: [], retained: [], changed: false };
const compare = (over: Partial<HistoryCompare> = {}): HistoryCompare => ({
  kind: "LISTING_HISTORY", view: "COMPARE", sku: "aquanest", marketplace: "AMAZON", product: "AquaNest bottle", swapped: false, identical: false,
  older: { id: "v1", number: 1, createdAt: "2026-10-01T09:00:00Z", sourceText: "Original listing written by Metrion", approved: false }, newer: { id: "v3", number: 3, createdAt: "2026-10-03T09:00:00Z", sourceText: "Your own edit: bullet 2", approved: false },
  sectionsChanged: { title: true, bullets: true, description: false, keywords: true, backendTerms: false, hashtags: false },
  title: { changed: true, ops: [{ op: "equal", old: "AquaNest Steel", new: "AquaNest Steel" }, { op: "insert", old: "", new: "Insulated" }, { op: "equal", old: "Bottle", new: "Bottle" }], addedWords: ["Insulated"], removedWords: [], old: "AquaNest Steel Bottle", new: "AquaNest Steel Insulated Bottle",
    oldLength: { characters: 21, words: 3 }, newLength: { characters: 31, words: 4 }, characterDelta: 10, attributes: { removed: [{ attribute: "Material", value: "stainless steel" }], introduced: [] } },
  bullets: { changed: true, counts: { unchanged: 1, reordered: 0, modified: 1, added: 1, removed: 0 }, items: [
    { status: "modified", old: "Holds 1 litre", new: "Holds 1 litre of water", oldPosition: 1, newPosition: 1, diff: { changed: true, ops: [{ op: "equal", old: "Holds 1 litre", new: "Holds 1 litre" }, { op: "insert", old: "", new: "of water" }], addedWords: ["of", "water"], removedWords: [], old: "", new: "", oldLength: { characters: 0, words: 0 }, newLength: { characters: 0, words: 0 }, characterDelta: 0 } },
    { status: "added", old: null, new: "Keeps drinks cold 24 hours", oldPosition: null, newPosition: 2 }, { status: "unchanged", old: "Silver finish", new: "Silver finish", oldPosition: 3, newPosition: 3 }] },
  description: { changed: false, counts: {}, items: [] }, keywords: { ...term, changed: true, added: ["travel bottle"], removed: ["reusable"] }, backendTerms: { ...term, available: false, reason: "NOT_USED_BY_THIS_MARKETPLACE" }, hashtags: { ...term, available: false, reason: "NOT_PART_OF_THESE_VERSIONS" },
  keywordMovement: { counts: { ADDED: 1, REMOVED: 0, MOVED: 1, RETAINED: 0 }, limits: "Search volume, ranking and demand are not assessed.", rows: [
    { keyword: "reusable", before: ["BULLET 1"], after: ["DESCRIPTION"], result: "MOVED", crossSection: true, trace: { state: "TRACEABLE", candidateId: "a:reusable", confidence: "MODERATE", evidence: "AVAILABLE" } },
    { keyword: "travel bottle", before: [], after: ["KEYWORDS"], result: "ADDED", crossSection: false, trace: { state: "NOT_A_RESEARCHED_CANDIDATE", candidateId: null, confidence: null, evidence: "UNAVAILABLE" } }] },
  audit: { available: true, reason: null, olderVerdict: "NEEDS_ATTENTION", newerVerdict: "BLOCKED", new: [{ check: "A04", severity: "BLOCKER", section: "BULLET 2", code: "UNSUPPORTED_CLAIM", explanation: "It says “keeps drinks cold 24 hours”.", correction: "Remove it." }], resolved: [], unresolved: [] },
  claims: { available: true, reason: null, new: [{ section: "BULLET 2", claim: "keeps drinks cold 24 hours", why: "It says “keeps drinks cold 24 hours”.", reference: "your confirmed product facts", nextStep: "Remove it.", auditCheck: "A04", auditCode: "UNSUPPORTED_CLAIM" }] },
  attributes: { available: true, removed: [], introduced: [] },
  performance: { state: "NOT_ASSESSED", never: "Sales, revenue, conversion, search ranking, visibility and demand are not assessed for a listing revision.", missing: "No comparable marketplace performance data is available.", note: "n" },
  notice: "These are differences in the saved text and in the saved audits. They do not show that a version performs better or worse, or that either was published.", published: "p", ...over,
});
const recs = (over: Partial<HistoryRecommendations> = {}): HistoryRecommendations => ({
  kind: "LISTING_HISTORY", view: "RECOMMEND", state: "RECOMMENDATIONS", versionNumber: 3, versionId: "v3", product: "AquaNest bottle", marketplace: "AMAZON", message: null, limitations: "Based on your confirmed facts and the saved text.",
  performance: compare().performance, recommendations: [{ code: "UNSUPPORTED_CLAIM", priority: "HIGH", recommendation: "Remove or confirm an unsupported claim", section: "BULLET 2", evidence: ["It says “keeps drinks cold”."], reason: "Your confirmed facts do not support it.", nextAction: "Remove it.", limitations: "Based on your confirmed facts and the saved text.", versionNumber: 3 }], ...over,
});
const api = (over: Partial<HistoryApi> = {}): HistoryApi => ({
  history: vi.fn(async () => list()), version: vi.fn(async () => detail), compare: vi.fn(async () => compare()), recommendations: vi.fn(async () => recs()), ...over,
});

describe("ListingHistoryCard (CMO 3.0 M7)", () => {
  it("recognises only a listing-history card", () => {
    expect(isHistoryCard(list())).toBe(true);
    expect(isHistoryCard({ kind: "LISTING" })).toBe(false);
    expect(isHistoryCard({ kind: "LISTING_HISTORY" })).toBe(false);
    expect(isHistoryCard(null)).toBe(false);
  });

  it("shows the multi-version timeline newest first with source, parent, dates and separate states (never published)", () => {
    render(<ListingHistoryCard card={list()} api={api()} onSend={() => {}} />);
    const rows = screen.getAllByTestId("history-version");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Version 3 (latest)");
    expect(rows[0]).toHaveTextContent("built from version 2");
    expect(rows[2]).toHaveTextContent("Original listing written by Metrion");
    expect(rows[1]).toHaveTextContent("✓ Approved for use in Metrion");
    expect(rows[0]).toHaveTextContent("○ Not approved for use");
    expect(rows[0]).toHaveTextContent("Published: unknown to Metrion");
    for (const r of rows) expect(r).not.toHaveTextContent(/Published: (yes|true)|is live|went live/i);
  });

  it("the latest version is not assumed approved", () => {
    render(<ListingHistoryCard card={list()} api={api()} onSend={() => {}} />);
    expect(screen.getAllByTestId("history-version")[0]).not.toHaveTextContent("✓ Approved");
  });

  it("shows a one-version history and an empty history with plain next steps", () => {
    const one = render(<ListingHistoryCard card={list([ver(1)])} api={api()} onSend={() => {}} />);
    expect(screen.getByTestId("history-one")).toHaveTextContent("one version so far");
    one.unmount();
    render(<ListingHistoryCard card={list([], { empty: true, groups: [] })} api={api()} onSend={() => {}} />);
    expect(screen.getByTestId("history-empty")).toHaveTextContent("No saved listing versions yet");
    expect(screen.queryByTestId("history-timeline")).toBeNull();
  });

  it("opens an older version in full with its own audit, then goes back to the history", async () => {
    const a = api();
    render(<ListingHistoryCard card={list()} api={a} onSend={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Open version 2" }));
    expect(await screen.findByText("Bullet 2:")).toBeInTheDocument();
    expect(a.version).toHaveBeenCalledWith("v2");
    expect(screen.getByText("Backend search terms:")).toBeInTheDocument();
    expect(screen.getByText("This version's own audit")).toBeInTheDocument();
    expect(screen.getByText(/bullets: “steel” repeats/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Back to history/ }));
    expect(screen.getByTestId("history-timeline")).toBeInTheDocument();
  });

  it("compares any two ticked versions (not only neighbours) and shows added, removed, modified text, keyword movement, audit and claims", async () => {
    const a = api();
    render(<ListingHistoryCard card={list()} api={a} onSend={() => {}} />);
    expect(screen.getByTestId("compare-selected")).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Select version 3 to compare"));
    await userEvent.click(screen.getByLabelText("Select version 1 to compare"));
    await userEvent.click(screen.getByTestId("compare-selected"));
    const view = await screen.findByTestId("history-compare");
    expect(a.compare).toHaveBeenCalledWith("v3", "v1");
    expect(within(view).getByText("Older: version 1")).toBeInTheDocument();
    expect(within(view).getByText("Newer: version 3")).toBeInTheDocument();
    expect(view.querySelector("ins")).toHaveTextContent("Insulated");
    expect(within(view).getByTestId("item-modified")).toHaveTextContent("~ Changed");
    expect(within(view).getByTestId("item-added")).toHaveTextContent("+ Added");
    expect(within(view).queryByTestId("item-unchanged")).toBeNull();
    expect(within(view).getByText(/Length 21 → 31 characters/)).toBeInTheDocument();
    const table = within(view).getByTestId("keyword-movement");
    expect(table).toHaveTextContent("↕ Moved");
    expect(table).toHaveTextContent("bullet 1");
    expect(table).toHaveTextContent("description");
    expect(table).toHaveTextContent("travel bottle (no saved evidence)");
    expect(within(view).getByTestId("new-claim")).toHaveTextContent("keeps drinks cold 24 hours");
    expect(within(view).getByTestId("new-claim")).toHaveTextContent("your confirmed product facts");
    expect(within(view).getByText(/1 new issues|New issues: 1/)).toBeInTheDocument();
    expect(within(view).getByText("Backend search terms: not used by this marketplace.")).toBeInTheDocument();
    expect(within(view).getByTestId("performance-state")).toHaveTextContent("Not assessed");
    expect(view).not.toHaveTextContent(/increase|boost|more sales|improved sales|better ranking/i);
  });

  it("says plainly when two versions are identical, and when the audits or claims cannot be checked", async () => {
    const same = compare({ identical: true, sectionsChanged: {}, audit: { available: false, reason: "AUDIT_MISSING_FOR_OLDER", new: [], resolved: [], unresolved: [] }, claims: { available: false, reason: "AUDIT_MISSING_FOR_NEWER", new: [] } });
    render(<ListingHistoryCard card={same} onSend={() => {}} />);
    expect(screen.getByTestId("compare-identical")).toHaveTextContent("identical text");
    expect(screen.getByText(/no saved audit, so the audits cannot be compared/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be checked/)).toBeInTheDocument();
  });

  it("shows that no new claim was introduced when none was", () => {
    render(<ListingHistoryCard card={compare({ claims: { available: true, reason: null, new: [] } })} onSend={() => {}} />);
    expect(screen.getByTestId("no-new-claims")).toBeInTheDocument();
    expect(screen.queryByTestId("new-claim")).toBeNull();
  });

  it("shows recommendations with section, evidence, reason, next step and limits, and says so when there is nothing to base them on", () => {
    const first = render(<ListingHistoryCard card={recs()} onSend={() => {}} />);
    const list1 = screen.getByTestId("recommendations");
    expect(list1).toHaveTextContent("✗ Fix first");
    expect(list1).toHaveTextContent("bullet 2, version 3");
    expect(list1).toHaveTextContent("Why: Your confirmed facts do not support it.");
    expect(list1).toHaveTextContent("It says “keeps drinks cold”.");
    expect(list1).toHaveTextContent("Next: Remove it.");
    expect(list1).toHaveTextContent("Limits:");
    first.unmount();
    render(<ListingHistoryCard card={recs({ state: "NO_EVIDENCE", recommendations: [], message: "There is not enough saved evidence to recommend anything." })} onSend={() => {}} />);
    expect(screen.getByTestId("recommend-none")).toHaveTextContent("not enough saved evidence");
  });

  it("filters by product and marketplace through the server and keeps the history readable on a failure", async () => {
    const two = list([ver(2, { sku: "other", product: "Other bottle", marketplace: "FLIPKART", id: "w1", number: 1 }), ver(1)], { groups: [
      { sku: "aquanest", product: "AquaNest bottle", marketplace: "AMAZON", versionCount: 1, latestNumber: 1, latestId: "v1" }, { sku: "other", product: "Other bottle", marketplace: "FLIPKART", versionCount: 1, latestNumber: 1, latestId: "w1" }] });
    const a = api({ history: vi.fn(async (q) => list([ver(1)], { filters: { sku: q.sku ?? null, marketplace: q.marketplace ?? null } })) });
    render(<ListingHistoryCard card={two} api={a} onSend={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText("Filter by product"), "aquanest");
    await waitFor(() => expect(a.history).toHaveBeenCalledWith(expect.objectContaining({ sku: "aquanest", marketplace: null })));
    await userEvent.selectOptions(await screen.findByLabelText("Filter by marketplace"), "AMAZON");
    await waitFor(() => expect(a.history).toHaveBeenLastCalledWith(expect.objectContaining({ sku: "aquanest", marketplace: "AMAZON" })));
  });

  it("shows loading, then an error with a retry that works", async () => {
    let release: (v: HistoryVersionDetail) => void = () => {};
    const slow = new Promise<HistoryVersionDetail>((r) => { release = r; });
    const version = vi.fn().mockReturnValueOnce(slow).mockRejectedValueOnce(new Error("boom")).mockResolvedValue(detail);
    render(<ListingHistoryCard card={list()} api={api({ version })} onSend={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Open version 2" }));
    expect(screen.getByTestId("history-loading")).toBeInTheDocument();
    release(detail);
    await screen.findByText("Bullet 2:");
    await userEvent.click(screen.getByRole("button", { name: /Back to history/ }));
    version.mockReset();
    version.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(detail);
    await userEvent.click(screen.getByRole("button", { name: "Open version 2" }));
    expect(await screen.findByTestId("history-error")).toHaveTextContent("I could not load that just now. Nothing was changed or used up.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Bullet 2:")).toBeInTheDocument();
  });

  it("names a missing version and an unauthorised request in plain words", async () => {
    const version = vi.fn().mockRejectedValueOnce(new ApiError(404, "Not found")).mockRejectedValueOnce(new ApiError(403, { code: "FORBIDDEN" }));
    render(<ListingHistoryCard card={list()} api={api({ version })} onSend={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Open version 2" }));
    expect(await screen.findByTestId("history-error")).toHaveTextContent("That version is no longer available");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("history-error")).toHaveTextContent("You do not have access to this listing history.");
  });

  it("shows a refused comparison reason from the server", async () => {
    const compareFn = vi.fn().mockRejectedValue(new ApiError(422, { detail: { code: "DIFFERENT_PRODUCT", detail: "Those versions belong to different products, so I will not compare them." } }));
    render(<ListingHistoryCard card={list()} api={api({ compare: compareFn })} onSend={() => {}} />);
    await userEvent.click(screen.getByLabelText("Select version 3 to compare"));
    await userEvent.click(screen.getByLabelText("Select version 2 to compare"));
    await userEvent.click(screen.getByTestId("compare-selected"));
    expect(await screen.findByTestId("history-error")).toHaveTextContent("different products");
  });

  it("asks a short question and sends the seller's choice as an ordinary message", async () => {
    const onSend = vi.fn();
    render(<ListingHistoryCard card={{ kind: "LISTING_HISTORY", view: "CLARIFY", question: "Which marketplace do you mean — Amazon or Flipkart?", options: [{ label: "Amazon", marketplace: "AMAZON" }, { label: "Flipkart", marketplace: "FLIPKART" }] }} onSend={onSend} />);
    expect(screen.getByText(/Which marketplace/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Flipkart" }));
    expect(onSend).toHaveBeenCalledWith("Flipkart");
  });

  it("is keyboard reachable: every action is a labelled button or checkbox", () => {
    render(<ListingHistoryCard card={list()} api={api()} onSend={() => {}} />);
    for (const n of [1, 2, 3]) {
      expect(screen.getByRole("button", { name: `Open version ${n}` })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: `Suggestions for version ${n}` })).toBeInTheDocument();
      expect(screen.getByRole("checkbox", { name: `Select version ${n} to compare` })).toBeInTheDocument();
    }
    expect(screen.getByRole("list", { name: "Versions, newest first" })).toBeInTheDocument();
  });
});
