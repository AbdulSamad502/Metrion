/** The Competitor Intelligence dashboard's data and wording (docs/specs/competitor-intelligence-agent.md §6.29).
 *
 * The dashboard is read-only (C32): it shows what CEO-CI investigations produced. Every figure arrives from the backend already decided (a price band is the engine's,
 * a count is the backend's); nothing here computes, rounds or estimates. Where a value is missing the cell says so and why, never a zero. */

import { formatPaise } from "@/lib/piShowcase";

export type Freshness = "FRESH" | "STALE" | "UNAVAILABLE";
export type PriceStatus = "VERIFIED" | "UNVERIFIED" | "UNAVAILABLE";
export type RelationshipClass = "SAME_PRODUCT" | "VARIANT" | "DIRECT_COMPETITOR" | "FUNCTIONAL_ALTERNATIVE" | "UNRELATED" | "UNKNOWN";

/** What Brain 1 (deterministic-engine.md 5.15.2) returned for one competitor's effective price and buyer total. Each figure carries its engine reference; an unavailable one says why. */
export type EngineCell = { valuePaise: number | null; engineResultRef: string; isAvailable: boolean; unavailableReason: string | null };
export type EffectivePriceView = {
  effective: EngineCell | null;
  buyerTotal: EngineCell | null;
  deliveryChargePaise: number | null;
  offers: Array<{ kind: string | null; amountPaise: number | null; conditional: boolean }>;
  excludedOffers: Array<{ kind: string | null; reason: string | null }>;
};

export type CiCompetitor = {
  id: string;
  findingId: string | null;
  effectivePrice: EffectivePriceView | null;
  label: string | null;
  marketplace: string;
  identityMatch: string | null;
  relationshipClass: RelationshipClass;
  relevanceBand: "HIGH" | "MEDIUM" | "LOW" | null;
  relevanceScore: number | null;
  relevanceProvisional: boolean | null;
  evidenceDate: string | null;
  freshness: Freshness;
  priceStatus: PriceStatus;
  listedPricePaise: number | null;
  availability: string | null;
  ratingValue: string | null;
  ratingCount: number | null;
  deltaPct: string | null;
  deltaDirection: string | null;
  openQuestions: number;
};

export type CiCandidate = {
  id: string;
  title: string | null;
  url: string | null;
  identityNote: string | null;
  marketplace: string | null;
  tier: "RAW" | "ANALYZED" | "RECOMMENDED";
  identityMatch: string | null;
  relationshipClass: RelationshipClass;
  relevanceBand: "HIGH" | "MEDIUM" | "LOW" | null;
  relevanceScore: number | null;
  relevanceProvisional: boolean | null;
  sellerDecision: "NONE" | "APPROVED" | "REJECTED";
  evidenceStatus: "AWAITING_EVIDENCE" | "EVIDENCE_BACKED";
};

export type CiChange = {
  competitorId: string;
  findingId: string | null;
  label: string | null;
  marketplace: string;
  kind: "PRICE" | "AVAILABILITY";
  deltaPaise: number;
  deltaPct: string;
  direction: string;
  availabilityChange: string | null;
  occurredAt: string | null;
  evidenceDate: string | null;
};

export type CiReviewInsight = {
  competitorId: string;
  findingId: string | null;
  label: string | null;
  complaintThemes: Array<{ theme: string; weight?: number | string }> | Record<string, number> | null;
  positiveThemes: Array<{ theme: string; weight?: number | string }> | Record<string, number> | null;
  reviewsConsidered: number | null;
  confidence: string;
  insightState: string;
  evidenceDate: string | null;
};

export type CiFinding = {
  id: string;
  type: "PRICE_CHANGE" | "AVAILABILITY_CHANGE" | "REVIEW_THEME" | "LISTING_GAP" | "DIFFERENTIATION" | "MARKET_POSITION" | "FRESHNESS" | "DISCOVERY_CANDIDATE";
  competitorId: string | null;
  freshness: Freshness;
  confidence: string;
  sellerConfirmation: "NOT_REQUIRED" | "PENDING" | "CONFIRMED" | "DECLINED";
  sampleSize: number | null;
  evidenceCount: number;
  createdAt: string | null;
  payload: Record<string, unknown>;
};

export type CiPending = { id: string; field: string; reason: string; competitorId: string | null; createdAt: string | null; expiresAt: string | null };

export type CiEventRow = { id: string; type: string; occurredAt: string | null; objectType: string | null; objectId: string | null; detail: Record<string, unknown> };

export type CiWorkspace = {
  asOf: string;
  products: Array<{ productId: string; title: string | null }>;
  selectedProductId: string | null;
  watchlist?: { limit: number; used: number; free: number };
  kpis: {
    trackedCount: number;
    verifiedCount: number;
    needsEvidenceCount: number;
    importantChangeCount: number;
    reviewInsightCount: number;
    pendingQuestionCount: number;
  };
  competitors: CiCompetitor[];
  candidates: CiCandidate[];
  reviewInsights: CiReviewInsight[];
  changes: CiChange[];
  pendingConfirmations: CiPending[];
  events: CiEventRow[];
  findings: CiFinding[];
  lastDiscovery: { status: string; partialReason: string | null; failedReason: string | null; provider: string | null; finishedAt: string | null; rawCandidateCount: number | null } | null;
};

export const RELATIONSHIP_LABEL: Record<RelationshipClass, string> = {
  SAME_PRODUCT: "Exact match",
  VARIANT: "Likely variant",
  DIRECT_COMPETITOR: "Direct competitor",
  FUNCTIONAL_ALTERNATIVE: "Functional alternative",
  UNRELATED: "Not a match",
  UNKNOWN: "Not classified yet",
};

export const FRESHNESS_LABEL: Record<Freshness, string> = { FRESH: "Fresh", STALE: "Getting old", UNAVAILABLE: "No current evidence" };
export const PRICE_STATUS_LABEL: Record<PriceStatus, string> = { VERIFIED: "Verified", UNVERIFIED: "Confirm in chat", UNAVAILABLE: "Needs a screenshot" };

const EVENT_LABEL: Record<string, string> = {
  EVIDENCE_RECEIVED: "Screenshot received",
  EVIDENCE_REJECTED_QUALITY: "Screenshot could not be used",
  EVIDENCE_DUPLICATE: "Duplicate screenshot recognised",
  FIELD_CONFIRMATION_REQUESTED: "Asked you to confirm a detail",
  FIELD_CONFIRMED: "You confirmed a detail",
  FIELD_CONFIRMATION_DECLINED: "You declined to confirm a detail",
  COMPETITOR_APPROVED: "Competitor approved",
  COMPETITOR_REJECTED: "Competitor rejected",
  COMPETITOR_ADDED: "Competitor added",
  COMPETITOR_REMOVED: "Competitor removed",
  DISCOVERY_RUN_STARTED: "Competitor search started",
  DISCOVERY_RUN_COMPLETED: "Competitor search finished",
  DISCOVERY_RUN_FAILED: "Competitor search failed",
  FINDING_CREATED: "New finding",
  ALERT_RAISED: "Alert raised",
  ALERT_SUPPRESSED_DEDUP: "Repeat alert held back",
  ALERT_HELD_QUIET_HOURS: "Alert held for quiet hours",
  ALERT_WITHHELD_STALE: "Alert withheld: the evidence got too old",
  MONITOR_RUN: "Competitors re-checked",
  CEO_INVESTIGATION_LINKED: "Linked to a CEO conversation",
};

export const eventLabel = (type: string): string => EVENT_LABEL[type] ?? type.toLowerCase().replace(/_/g, " ");

/** The activity log in plain words: one line per day, each kind of event counted ("12 details confirmed"), newest day first. Nothing is added: the counts are of the stored events. */
export function groupEvents(events: { type: string; occurredAt: string | null }[]): { day: string; items: { label: string; count: number }[] }[] {
  const days = new Map<string, Map<string, number>>();
  for (const e of events) {
    const day = (e.occurredAt ?? "").slice(0, 10);
    const m = days.get(day) ?? new Map<string, number>();
    const label = eventLabel(e.type);
    m.set(label, (m.get(label) ?? 0) + 1);
    days.set(day, m);
  }
  return [...days.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([day, m]) => ({ day, items: [...m.entries()].map(([label, count]) => ({ label, count })) }));
}

/** A tracked competitor group is a product, or a business-profile CATEGORY (its id is "category:<name>"): a category shows as "Category: Water bottles". */
export const productLabel = (p: { productId: string; title: string | null }): string => {
  if (p.title) return p.title;
  if (p.productId.startsWith("category:")) {
    const name = p.productId.slice("category:".length).trim();
    return `Category: ${name.charAt(0).toUpperCase()}${name.slice(1)}`;
  }
  return p.productId;
};

export function fmtDate(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "date not stated";
}

/** A stored timestamp for display ("18 Oct 2026, 5:30 pm"), or plain words when it is missing or unreadable. */
export function fmtDateTime(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })
    : "time not stated";
}

export function themeList(t: CiReviewInsight["complaintThemes"]): string[] {
  if (!t) return [];
  if (Array.isArray(t)) return t.map((x) => (typeof x === "string" ? x : x.theme)).filter(Boolean);
  return Object.keys(t);
}

/** The CEO Hub links the dashboard's shortcuts and "Ask CEO" buttons open. They carry only plain words and the product's own name; the CEO resolves it against the
 * seller's own products on the server, and the seller sends the message (spec D14). Nothing is run by following one. */
export type AskIntent = "research" | "monitor" | "reviews" | "competitor" | "candidates" | "finding" | "track" | "verify" | "stop" | "trackone" | "reviewsfor" | "compare" | "confirm";

export function askDraft(intent: AskIntent, subject?: string | null): string {
  const about = subject?.trim() ? ` for my ${subject.trim()}` : "";
  switch (intent) {
    case "research":
      return `Find competitors${about}`;
    case "monitor":
      return `Monitor my competitors${about}`;
    case "track":
      return `Track a competitor${about}`;
    case "verify":
      return `Verify ${subject?.trim() ?? "this competitor"}`;
    case "stop":
      return `Stop tracking ${subject?.trim() ?? "this competitor"}`;
    case "trackone":
      return `Track ${subject?.trim() ?? "this competitor"}`;
    case "reviewsfor":
      return `These are reviews of ${subject?.trim() ?? "this competitor"}. Identify customer complaints, praise and how many reviews you can read.`;
    case "compare":
      return "Compare my price with all my competitors";
    case "confirm":
      return "Show me what I need to confirm";
    case "reviews":
      return `What do customers complain about at my competitors${about}`;
    case "competitor":
      return `Tell me about my competitor ${subject?.trim() ?? ""}`.trim();
    case "candidates":
      return `Which of the competitors you found${about} should I track`;
    case "finding":
      return `Tell me about this finding${subject?.trim() ? ` about ${subject.trim()}` : ""}`;
  }
}

export function askHref(intent: AskIntent, subject?: string | null): string {
  const params = new URLSearchParams({ ask: intent });
  if (subject?.trim()) params.set("about", subject.trim());
  return `/dashboard/ceo-hub?${params.toString()}`;
}

/** Ask CEO on one stored finding: carries the finding's own id (and the product it is about); the CEO re-reads the stored finding and its evidence for this tenant (spec C46). */
export function askFindingHref(findingId: string, productId: string | null, subject?: string | null): string {
  const params = new URLSearchParams({ ask: "finding", finding: findingId });
  if (productId) params.set("sku", productId);
  if (subject?.trim()) params.set("about", subject.trim());
  return `/dashboard/ceo-hub?${params.toString()}`;
}

/** Reads a hub URL's `ask`/`about` back into the draft message (the inverse of `askHref`). An unknown intent yields no draft. */
export function draftFromParams(ask: string | null, about: string | null): string | null {
  if (ask === "research" || ask === "monitor" || ask === "track" || ask === "verify" || ask === "stop" || ask === "trackone" || ask === "reviewsfor" || ask === "compare" || ask === "confirm" || ask === "reviews" || ask === "competitor" || ask === "candidates" || ask === "finding") return askDraft(ask, about);
  return null;
}


/** One finding in plain words, from its stored payload only (ids, derived facts and dates; never review text). Every figure is one CI stored; none is computed here. */
export function findingText(f: CiFinding): string {
  const p = f.payload as Record<string, string | number | null | undefined | Array<{ theme: string }>>;
  const label = (p.label as string | null | undefined) ?? "A competitor";
  const date = fmtDate((p.evidenceDate as string | null | undefined) ?? null);
  switch (f.type) {
    case "PRICE_CHANGE": {
      const down = p.direction === "DECREASE";
      return `${label}: price ${down ? "dropped" : "rose"} ${String(p.deltaPct ?? "").replace("-", "")}% (from ${formatPaise(p.fromPricePaise as number | null)} to ${formatPaise(p.toPricePaise as number | null)}), screenshot of ${date}`;
    }
    case "AVAILABILITY_CHANGE":
      return `${label}: stock changed (${String(p.availabilityChange ?? "changed").toLowerCase().replace(/_/g, " ")}), screenshot of ${date}`;
    case "REVIEW_THEME": {
      const themes = themeList(p.complaintThemes as CiReviewInsight["complaintThemes"]).slice(0, 2);
      return `${label}'s customers complain about ${themes.length ? themes.join(" and ") : "nothing recurring I could find"}${f.sampleSize ? ` (${f.sampleSize} reviews read)` : ""}`;
    }
    case "FRESHNESS":
      return `${label}: the newest screenshot is from ${date}. Send a fresh one to compare`;
    default:
      return `${label}: ${f.type.toLowerCase().replace(/_/g, " ")}`;
  }
}


const UNAVAILABLE_WORDS: Record<string, string> = {
  DELIVERY_CHARGE_NOT_OBSERVED: "delivery charge not confirmed",
  LISTED_PRICE_NOT_OBSERVED: "no listed price",
  DISCOUNTS_EXCEED_LISTED_PRICE: "the discounts do not add up",
};

export const unavailableWords = (reason: string | null | undefined): string => (reason ? UNAVAILABLE_WORDS[reason] ?? reason.toLowerCase().replace(/_/g, " ") : "not available");

/** The offers a competitor shows, in words, with the ones that are not counted named as such (a conditional offer is never subtracted from a price). */
export function offersLine(v: EffectivePriceView): string | null {
  if (v.offers.length === 0) return null;
  const counted = v.offers.filter((o) => !o.conditional && o.amountPaise !== null).length;
  const notCounted = v.offers.length - counted;
  const kinds = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  return [counted ? `${kinds(counted, "offer")} counted` : null, notCounted ? `${kinds(notCounted, "offer")} not counted (needs a card or a condition)` : null].filter(Boolean).join(", ");
}
