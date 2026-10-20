/** Business profile (docs/specs/business-profile.md): the eight mandatory fields, their options and the client-side checks. The server is the authority — these
 * checks only save a round trip and mirror its rules (every field required, same bounds); a save the server refuses is shown to the seller in plain words. */

export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";
export type PriceSegment = "BUDGET" | "MID_RANGE" | "PREMIUM";
export type BusinessStage = "JUST_STARTING" | "GROWING" | "ESTABLISHED";

export type BusinessProfileForm = {
  business_name: string;
  description: string;
  categories: string;
  marketplaces: Marketplace[];
  price_segment: PriceSegment | "";
  target_customer: string;
  business_stage: BusinessStage | "";
  state: string;
};

/** The shape GET /api/v1/business-profile returns (camelCase). */
export type BusinessProfileRead = {
  businessName: string;
  description: string;
  categories: string;
  marketplaces: Marketplace[];
  priceSegment: PriceSegment;
  targetCustomer: string;
  businessStage: BusinessStage;
  state: string;
  updatedAt: string;
};
export type BusinessProfileResponse = { profile: BusinessProfileRead | null; complete: boolean; suggestedName: string | null };

export const EMPTY_FORM: BusinessProfileForm = {
  business_name: "",
  description: "",
  categories: "",
  marketplaces: [],
  price_segment: "",
  target_customer: "",
  business_stage: "",
  state: "",
};

export const MARKETPLACE_OPTIONS: { value: Marketplace; label: string }[] = [
  { value: "AMAZON", label: "Amazon" },
  { value: "FLIPKART", label: "Flipkart" },
  { value: "MEESHO", label: "Meesho" },
];
export const PRICE_OPTIONS: { value: PriceSegment; label: string; hint: string }[] = [
  { value: "BUDGET", label: "Budget", hint: "Priced to win on value" },
  { value: "MID_RANGE", label: "Mid-range", hint: "Everyday quality at a fair price" },
  { value: "PREMIUM", label: "Premium", hint: "Higher price for higher quality or brand" },
];
export const STAGE_OPTIONS: { value: BusinessStage; label: string; hint: string }[] = [
  { value: "JUST_STARTING", label: "Just starting out", hint: "Early days, few orders so far" },
  { value: "GROWING", label: "Growing", hint: "Selling steadily and scaling up" },
  { value: "ESTABLISHED", label: "Established", hint: "A steady, mature business" },
];
export const STATES = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
  "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
  "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
  "Ladakh", "Lakshadweep", "Puducherry",
];

export type FieldKey = keyof BusinessProfileForm;

/** One short question per slide, in this order. */
export const STEPS: { key: FieldKey; title: string; help: string }[] = [
  { key: "business_name", title: "What is your business called?", help: "The name your customers know you by." },
  { key: "description", title: "What does your business do?", help: "One or two sentences, in your own words." },
  { key: "categories", title: "What do you sell?", help: "Your main product categories, for example “kitchen storage, steel bottles”." },
  { key: "marketplaces", title: "Where do you sell?", help: "Choose every marketplace you sell on." },
  { key: "price_segment", title: "Which price segment are you in?", help: "Where most of your products sit." },
  { key: "target_customer", title: "Who are your customers?", help: "For example “young urban families” or “college students”." },
  { key: "business_stage", title: "How would you describe your business today?", help: "This helps us pitch advice at the right level." },
  { key: "state", title: "Which state are you based in?", help: "Where your business operates from." },
];

const BOUNDS: Partial<Record<FieldKey, [string, number, number]>> = {
  business_name: ["Business name", 1, 120],
  description: ["Description", 10, 300],
  categories: ["What you sell", 2, 150],
  target_customer: ["Target customer", 2, 150],
};
export const MAX_LENGTH: Partial<Record<FieldKey, number>> = { business_name: 120, description: 300, categories: 150, target_customer: 150 };

/** The first problem with a field, in plain words, or null when it is fine. Every field is mandatory. */
export function fieldError(key: FieldKey, form: BusinessProfileForm): string | null {
  const b = BOUNDS[key];
  if (b) {
    const v = form[key] as string;
    const t = v.replace(/\s+/g, " ").trim();
    const [label, lo, hi] = b;
    if (!t) return `${label} is required.`;
    if (t.length < lo) return `${label} must be at least ${lo} characters.`;
    if (t.length > hi) return `${label} must be at most ${hi} characters.`;
    if (/[<>]/.test(v)) return `${label} cannot contain < or >.`;
    return null;
  }
  if (key === "marketplaces") return form.marketplaces.length === 0 ? "Choose at least one marketplace." : null;
  if (key === "price_segment") return form.price_segment ? null : "Choose a price segment.";
  if (key === "business_stage") return form.business_stage ? null : "Choose a business stage.";
  if (key === "state") return STATES.includes(form.state) ? null : "Choose a state or union territory.";
  return null;
}

/** Every field's problem; an empty object means the form may be saved. */
export function formErrors(form: BusinessProfileForm): Partial<Record<FieldKey, string>> {
  const out: Partial<Record<FieldKey, string>> = {};
  for (const s of STEPS) {
    const e = fieldError(s.key, form);
    if (e) out[s.key] = e;
  }
  return out;
}

export function fromRead(p: BusinessProfileRead): BusinessProfileForm {
  return {
    business_name: p.businessName,
    description: p.description,
    categories: p.categories,
    marketplaces: [...p.marketplaces],
    price_segment: p.priceSegment,
    target_customer: p.targetCustomer,
    business_stage: p.businessStage,
    state: p.state,
  };
}

/** The request body: only complete forms are ever turned into one (the caller checks `formErrors` first). */
export function toBody(form: BusinessProfileForm): Record<string, unknown> {
  return { ...form, business_name: form.business_name.trim(), description: form.description.trim(), categories: form.categories.trim(), target_customer: form.target_customer.trim() };
}
