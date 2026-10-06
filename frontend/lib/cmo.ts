/** Typed client for the Slim CMO routes (`backend/src/backend/api/v1/cmo.py`). Every call is a real backend call; nothing in the
 * CMO workspace is mocked. CMO is recommend-only: there is no function here that publishes or updates anything on a marketplace.
 *
 * Money: the only amount the seller can enter is an optional target price, typed in rupees and converted to INTEGER PAISE at the
 * edge with string arithmetic (no floats, no rounding) — the backend never receives or returns a rupee decimal. */

import { ApiError, apiFetch, apiFetchForm } from "@/lib/api";

export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";
export const MARKETPLACES: { id: Marketplace; label: string }[] = [
  { id: "AMAZON", label: "Amazon" },
  { id: "FLIPKART", label: "Flipkart" },
  { id: "MEESHO", label: "Meesho" },
];
export const marketplaceLabel = (m: string | null | undefined): string => MARKETPLACES.find((x) => x.id === m)?.label ?? (m ?? "—");

export type GetToken = () => Promise<string | null>;

// ------------------------------------------------------------------------------------------------ money at the edge
/** "499", "499.5", "499.50" -> paise as an integer. Anything else (negative, 3 decimals, text, empty) -> null. */
export function rupeesToPaise(input: string): number | null {
  const m = /^\s*(\d{1,9})(?:\.(\d{1,2}))?\s*$/.exec(input);
  if (!m) return null;
  const whole = Number.parseInt(m[1], 10);
  const frac = Number.parseInt((m[2] ?? "").padEnd(2, "0") || "0", 10);
  return whole * 100 + frac;
}

export function paiseToRupees(paise: number): string {
  const whole = Math.trunc(paise / 100);
  const frac = String(paise % 100).padStart(2, "0");
  return `₹${whole}.${frac}`;
}

export function newRequestKey(prefix: string): string {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${id}`.slice(0, 128);
}

// ------------------------------------------------------------------------------------------------ intake
export type AttributePair = { name: string; value: string };

export type ProductIntake = {
  sku: string;
  productName: string;
  brand: string;
  categoryHint: string;
  attributes: AttributePair[];
  notes: string;
  targetPriceRupees: string;
  imageAnalysisId: string | null;
  textOnlyConfirmed: boolean;
};

export const EMPTY_INTAKE: ProductIntake = {
  sku: "", productName: "", brand: "", categoryHint: "", attributes: [], notes: "", targetPriceRupees: "", imageAnalysisId: null, textOnlyConfirmed: false,
};

export type IntakeProblem = { field: string; message: string };

export function validateIntake(i: ProductIntake): IntakeProblem[] {
  const out: IntakeProblem[] = [];
  if (i.targetPriceRupees.trim() && rupeesToPaise(i.targetPriceRupees) === null) {
    out.push({ field: "targetPrice", message: "Enter the price in rupees, for example 499 or 499.50." });
  }
  if (!i.productName.trim() && !i.brand.trim() && i.attributes.length === 0 && !i.imageAnalysisId) {
    out.push({ field: "product", message: "Add at least a product name, a brand, an attribute or a photo so there is something to write about." });
  }
  return out;
}

/** The declared intake fields only — never a tenant id, meter or cap (the backend rejects those). */
export function intakeBody(i: ProductIntake, requestKey: string): Record<string, unknown> {
  const body: Record<string, unknown> = { request_key: requestKey };
  const text = (k: string, v: string) => {
    if (v.trim()) body[k] = v.trim();
  };
  text("sku", i.sku);
  text("product_name", i.productName);
  text("brand", i.brand);
  text("category_hint", i.categoryHint);
  const attrs = i.attributes.filter((a) => a.name.trim() && a.value.trim()).map((a) => ({ name: a.name.trim(), value: a.value.trim() }));
  if (attrs.length) body.attributes = attrs;
  if (i.notes.trim()) body.notes = i.notes.split("\n").map((n) => n.trim()).filter(Boolean);
  const paise = i.targetPriceRupees.trim() ? rupeesToPaise(i.targetPriceRupees) : null;
  if (paise !== null) body.target_price_paise = paise;
  if (i.imageAnalysisId) body.image_analysis_id = i.imageAnalysisId;
  if (i.textOnlyConfirmed) body.text_only_confirmed = true;
  return body;
}

// ------------------------------------------------------------------------------------------------ errors in plain words
export type CmoProblem = { title: string; body: string; kind: "permission" | "quota" | "config" | "changed" | "validation" | "busy" | "other" };

type Detail = { code?: string; detail?: string; reason?: string; meterCode?: string; remaining?: number; cap?: number; missing?: string[]; invalid?: { key: string; reason: string }[] };

function asDetail(d: unknown): Detail {
  return d && typeof d === "object" ? (d as Detail) : {};
}

export function explainCmoError(e: unknown): CmoProblem {
  if (!(e instanceof ApiError)) return { title: "Could not reach the server", body: "Check your connection and try again. Nothing was changed.", kind: "other" };
  const d = asDetail(e.detail);
  const text = typeof e.detail === "string" ? e.detail : "";
  switch (e.status) {
    case 401:
      return { title: "You are signed out", body: "Sign in again to continue.", kind: "permission" };
    case 403: {
      const key = /permission: ([a-z._]+)/i.exec(text)?.[1];
      return {
        title: "You do not have access to this",
        body: key ? `This needs the "${key}" permission. Ask the account owner to grant it to you.` : "Ask the account owner to grant you access to the CMO agent.",
        kind: "permission",
      };
    }
    case 402:
      return {
        title: "Your plan limit for this is used up",
        body: `Nothing was run or charged.${typeof d.remaining === "number" ? ` Units remaining: ${d.remaining}.` : ""}${d.meterCode ? ` (${d.meterCode})` : ""}`,
        kind: "quota",
      };
    case 404:
      return { title: "Not found", body: "That item does not exist for your account.", kind: "other" };
    case 409:
      if (d.code === "PLAN_CHANGED") return { title: "The plan changed", body: "Your confirmed niche terms or settings changed since the preview. Review the new preview before sending.", kind: "changed" };
      if (d.code === "REQUEST_IN_PROGRESS") return { title: "Already running", body: "An identical request is still in progress. Wait a moment and check again.", kind: "busy" };
      return { title: "Blocked", body: d.detail ?? d.code ?? "This action is blocked right now.", kind: "other" };
    case 413:
      return { title: "File too large", body: "Choose a smaller picture.", kind: "validation" };
    case 415:
      return { title: "Unsupported picture", body: "Use a normal JPEG, PNG or WebP photo.", kind: "validation" };
    case 422:
      if (d.code === "NICHE_TERM_REFUSED") return { title: "That term cannot be used", body: "Niche terms cannot contain contact details, web addresses, tax or order numbers, or be only digits.", kind: "validation" };
      if (d.code === "TOO_MANY_CONFIRMED_TERMS") return { title: "Too many confirmed terms", body: "Reject or edit one of your confirmed terms first.", kind: "validation" };
      return { title: "Please check the form", body: d.detail ?? d.code ?? (text || "Some details are missing or invalid."), kind: "validation" };
    case 429:
      return { title: "Slow down a little", body: "Too many requests in a short time. Try again shortly.", kind: "busy" };
    case 503:
      if (d.code === "CONFIG_MISSING") {
        const keys = [...(d.missing ?? []), ...(d.invalid ?? []).map((x) => x.key)];
        return { title: "Not set up yet", body: `An administrator must finish setting up this feature${keys.length ? ` (${keys.join(", ")})` : ""}. Nothing was sent and nothing was charged.`, kind: "config" };
      }
      return { title: "Not set up yet", body: "This feature is not configured on the server yet. Nothing was sent and nothing was charged.", kind: "config" };
    default:
      return { title: "Something went wrong", body: "Please try again. If it keeps happening, contact support.", kind: "other" };
  }
}

// ------------------------------------------------------------------------------------------------ response types
export type Constraint = { sourceUrl: string | null; verifiedAt: string | null; version: number | null } | null;
export type Failure = { code: string; reason: string | null; missingFacts: string[] };

export type TitleOption = { id: string; rank: number; text: string; charCount: number };
export type ArtefactBase = { id: string; outputType: string; marketplace: Marketplace | null; status: "COMPLETE" | "FAILED"; reused: boolean; agentRunId: string | null; failure?: Failure };
export type RuleFields = { constraint?: Constraint; unverifiedLimits?: string[]; countRule?: string | null };
export type TitleSetArtefact = ArtefactBase & RuleFields & { options?: TitleOption[]; expectedOptionCount?: number | null; deliveredOptionCount?: number | null; short?: boolean; shortLabel?: string | null };
export type CopyArtefact = ArtefactBase & RuleFields & {
  description?: string | null; bullets?: string[]; keywords?: string[]; descriptionType?: string | null; terms?: string[]; joined?: string | null;
  byteCount?: number | null; maxBytes?: number | null; hashtags?: string[]; label?: string | null; maxSetSize?: number | null;
  structuredFields?: { state: string; reason: string | null; fields: string[] };
};
export type CatalogAttributeAnswer = {
  attribute: string; value: string | null; basis: "SELLER_PROVIDED" | "IMAGE_OBSERVED" | "ESTIMATED" | "SOURCE_DERIVED" | "UNKNOWN"; claimEligible: boolean;
  requiresSellerInput: boolean; note: string | null; suggestion: { value: string | null; text: string | null } | null; estimate: Record<string, unknown> | null;
};
export type CatalogArtefact = ArtefactBase & { attributes?: CatalogAttributeAnswer[]; basisCounts?: Record<string, number>; disclaimer?: string | null };
export type RunResponse<T extends ArtefactBase = ArtefactBase> = { runStatus: string; unitsBilled: number; agentRunId: string | null; artefacts: T[] };

export type ImageUpload = { assetId: string; created: boolean; width: number; height: number; contentType: string; unitsBilled: number };
export type ImageAttribute = { name: string; value: string | null; basis: string; trustState: string; note: string | null };
export type ImageAnalysis = { analysisId: string; state: string; reason: string | null; reused: boolean; trustGate: { open: boolean }; attributes: ImageAttribute[]; unitsBilled: number };

export type NicheTerm = { id: string; term: string; origin: string; originNote: string | null; status: "SUGGESTED" | "CONFIRMED" | "REJECTED"; documentFrequency?: number };
export type NicheSuggestResponse = { status: "OK" | "UNAVAILABLE"; reason: string | null; titlesRead: number; suggestions: NicheTerm[]; confirmed: NicheTerm[] };
export type NicheConfirmResponse = { confirmed: NicheTerm[]; suggestions: NicheTerm[]; rejectedCount: number };

export type TrendQuery = { queryId: string; section: string; provider: string; templateId: string; query: string; params: Record<string, string | number> };
export type TrendPreview = {
  digest: string; queries: TrendQuery[]; sections: string[]; marketplaces: string[]; unavailableSections: Record<string, string>; unresearchedTerms: string[];
  skippedByBudget: string[][]; budget: Record<string, unknown>; byProvider: Record<string, number>; notice: string;
};
export type TrendSource = {
  url: string; title: string | null; source_type: string; published_at: string | null; retrieved_at: string; independence_key: string; source_class: string; recency: string | null; collapsed_into: string | null;
};
export type TrendFinding = {
  finding_id: string; section: string; theme: string; summary: string; sources: TrendSource[]; mention_count: number; independent_source_count: number;
  freshest_published_at: string | null; recency_class: string; corroboration: string | null; corroboration_label: string; is_stale: boolean; limitation_note: string;
  attention_metrics?: { kind: string; value: number; source_url: string; as_reported_by: string; as_of: string }[]; attention_note?: string;
  news_kind?: string; source_class?: string; buzz_kind?: string; relation_to_niche?: string;
  claim_status?: string; attributed_to?: string[]; policy_risk?: string | null; policy_risk_basis?: string | null; policy_check_line?: string;
  suggested_actions_allowed?: string[]; caution?: boolean;
};
export type TrendSectionData = { state: "COMPLETE" | "PARTIAL" | "UNAVAILABLE"; reason: string | null; findings: TrendFinding[] };
export type TrendInterpretation = { label: string; items: { statement: string; derived_from_finding_ids: string[]; action_type: string }[]; note: string | null };
export type TrendEvidence = {
  sources: (TrendSource & { cited_by: string[] })[]; per_finding: { finding_id: string; independent_source_count: number; mention_count: number; recency_class: string; corroboration: string | null; is_stale: boolean }[];
  degraded_sections: { section: string; reason: string }[]; providers_and_modes_used: string[]; provider_accounting: Record<string, unknown>; unresearched_confirmed_terms: string[];
  withheld_for_instruction_like_text: number; dropped_by_source_cap: number; interpretation: Record<string, number>; data_gaps: string[];
};
export type TrendReport = {
  sections: Record<string, TrendSectionData>; interpretation: TrendInterpretation; evidence: TrendEvidence; outbound_queries: TrendQuery[]; sections_requested: string[];
};
export type TrendRun = {
  generationId: string; status: "COMPLETE" | "FAILED"; reused: boolean; failureReason: string | null; createdAt: string; unitsBilled: { cmo: number; shared: number };
  agentRunId: string | null; report: TrendReport | null;
};
export type TrendListItem = { generationId: string; status: string; failureReason: string | null; createdAt: string };

// ------------------------------------------------------------------------------------------------ calls
const BASE = "/api/v1/cmo";

async function post<T>(getToken: GetToken, path: string, body: unknown): Promise<T> {
  return apiFetch<T>(`${BASE}${path}`, await getToken(), { method: "POST", body: JSON.stringify(body) });
}
async function get<T>(getToken: GetToken, path: string): Promise<T> {
  return apiFetch<T>(`${BASE}${path}`, await getToken());
}

export const cmo = {
  titleSets: (t: GetToken, intake: ProductIntake, key: string, marketplaces: Marketplace[]) =>
    post<RunResponse<TitleSetArtefact>>(t, "/title-sets", { ...intakeBody(intake, key), marketplaces }),
  approveTitle: (t: GetToken, generationId: string, opts: { optionId?: string; editedText?: string }) =>
    post<{ approvalId: string; generationId: string; optionId: string | null; approvedText: string; editedBySeller: boolean }>(t, "/title-approvals", {
      generation_id: generationId, ...(opts.optionId ? { option_id: opts.optionId } : {}), ...(opts.editedText ? { edited_text: opts.editedText } : {}),
    }),
  listingCopy: (t: GetToken, intake: ProductIntake, key: string, marketplace: Marketplace, anchor: { approvalId?: string; sellerTitle?: string }) =>
    post<RunResponse<CopyArtefact>>(t, "/listing-copy", { ...intakeBody(intake, key), marketplace, ...(anchor.approvalId ? { approval_id: anchor.approvalId } : {}), ...(anchor.sellerTitle ? { seller_title: anchor.sellerTitle } : {}) }),
  component: (t: GetToken, kind: "description" | "bullets" | "keywords" | "backend-terms", intake: ProductIntake, key: string, marketplace: Marketplace, anchor: { approvalId?: string; sellerTitle?: string }) =>
    post<RunResponse<CopyArtefact>>(t, `/${kind}`, { ...intakeBody(intake, key), marketplace, ...(anchor.approvalId ? { approval_id: anchor.approvalId } : {}), ...(anchor.sellerTitle ? { seller_title: anchor.sellerTitle } : {}) }),
  hashtags: (t: GetToken, intake: ProductIntake, key: string, marketplace: Marketplace | null) =>
    post<RunResponse<CopyArtefact>>(t, "/hashtags", { ...intakeBody(intake, key), ...(marketplace ? { marketplace } : {}) }),
  catalog: (t: GetToken, intake: ProductIntake, key: string, questions: string[], marketplaces: Marketplace[]) =>
    post<RunResponse<CatalogArtefact>>(t, "/catalog-answers", { ...intakeBody(intake, key), questions, marketplaces }),
  uploadImage: async (t: GetToken, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return apiFetchForm<ImageUpload>(`${BASE}/images`, await t(), fd);
  },
  analyzeImage: (t: GetToken, assetId: string) => post<ImageAnalysis>(t, "/image-analyses", { asset_id: assetId }),
  confirmHint: (t: GetToken, analysisId: string, attributeName: string, sku: string, confirmedValue: string | null) =>
    post<{ factId: string; created: boolean; unitsBilled: number }>(t, "/image-hints/confirm", { analysis_id: analysisId, attribute_name: attributeName, sku, confirmed_value: confirmedValue }),
  suggestNiche: (t: GetToken) => post<NicheSuggestResponse>(t, "/niche-terms/suggest", undefined),
  listNiche: (t: GetToken) => get<{ terms: NicheTerm[] }>(t, "/niche-terms"),
  confirmNiche: (t: GetToken, decisions: { term_id: string; decision: "CONFIRM" | "REJECT" | "EDIT"; new_text?: string }[], newTerms: string[]) =>
    post<NicheConfirmResponse>(t, "/niche-terms/confirm", { decisions, new_terms: newTerms }),
  trendPreview: (t: GetToken, sections: string[], marketplaces: Marketplace[]) => post<TrendPreview>(t, "/market-trends/preview", { sections, marketplaces }),
  trendRun: (t: GetToken, key: string, digest: string, sections: string[], marketplaces: Marketplace[]) =>
    post<TrendRun>(t, "/market-trends", { request_key: key, plan_digest: digest, sections, marketplaces }),
  trendList: (t: GetToken) => get<{ reports: TrendListItem[] }>(t, "/market-trends"),
  trendGet: (t: GetToken, id: string) => get<TrendRun>(t, `/market-trends/${id}`),
};
