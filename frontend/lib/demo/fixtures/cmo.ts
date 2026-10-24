import type { ComplianceSummary, CopyPack, HashtagSet, Marketplace, ShowcaseProduct, ShowcaseTitle, TitleUsage, TitlesPage, TrendReport } from "@/lib/cmoShowcase";
import type { DemoRoute } from "../respond";
import { isoDaysAgo } from "./dates";

/** SAMPLE Slim CMO results for a fictional kitchen-storage seller ("Sample Home Goods"). Titles, copy and trend notes are made-up recommendation text for the
 * seller to copy; Metrion never publishes them. Character counts are the length of the sample text written here; limits and approvals are sample values. */

const origin = { investigationId: null, turnId: null, kind: "CEO_CHAT" as const };
const MAX: Record<Marketplace, number> = { AMAZON: 200, FLIPKART: 150, MEESHO: 100 };
const SOURCE = { sourceUrl: "https://rules.example.test/titles", verifiedAt: isoDaysAgo(20) };

type ProductSpec = { sku: string; label: string; days: number; titles: Record<Marketplace, { text: string; approved: boolean; usage: TitleUsage | null }[]>; bullets: string[]; description: string; backend: string; tags: string[] };

const PRODUCTS: ProductSpec[] = [
  {
    sku: "SHG-KC-6",
    label: "Steel Container Set, 6 pieces",
    days: 2,
    titles: {
      AMAZON: [
        { text: "Sample Home Goods Stainless Steel Airtight Container Set of 6, Kitchen Storage for Atta, Rice and Pulses, Leakproof Lids, Rust-Free", approved: true, usage: { copied: 4, markedUsed: 1, since: isoDaysAgo(14) } },
        { text: "Sample Home Goods Steel Storage Containers 6 Pc Set, Airtight and Stackable for Kitchen, Dishwasher Safe", approved: false, usage: { copied: 1, since: isoDaysAgo(14) } },
        { text: "Sample Home Goods 6-Piece Steel Kitchen Container Set with Airtight Lids", approved: false, usage: null },
      ],
      FLIPKART: [
        { text: "Sample Home Goods Steel Airtight Container Set of 6 for Kitchen Storage", approved: true, usage: { copied: 2, markedUsed: 1, since: isoDaysAgo(14) } },
        { text: "Sample Home Goods Stackable Steel Containers, 6 Pc, Leakproof", approved: false, usage: null },
      ],
      MEESHO: [
        { text: "Steel Airtight Container Set of 6 Kitchen Storage", approved: false, usage: { copied: 3, since: isoDaysAgo(14) } },
        { text: "6 Pc Steel Storage Container Set Leakproof", approved: false, usage: null },
      ],
    },
    bullets: [
      "Food-grade stainless steel that does not hold odours or stain, so atta, rice and pulses stay fresh.",
      "Airtight lids with a silicone ring keep out moisture and insects through the monsoon.",
      "Six sizes that stack neatly and fit a standard kitchen shelf.",
      "Easy to clean by hand or in a dishwasher.",
      "Plain finish that suits any kitchen.",
    ],
    description: "A set of six stainless steel storage containers for everyday kitchen use. The airtight lids keep grains and pulses dry, the sizes stack to save shelf space, and the steel does not pick up smells. This is sample listing text for illustration.",
    backend: "steel container set airtight kitchen storage atta rice pulses",
    tags: ["#KitchenStorage", "#SteelContainers", "#KitchenOrganisation", "#AirtightJars", "#HomeKitchenIndia"],
  },
  {
    sku: "SHG-GJ-4",
    label: "Glass Jar Set with Bamboo Lids, 4 pieces",
    days: 6,
    titles: {
      AMAZON: [
        { text: "Sample Home Goods Borosilicate Glass Jars with Bamboo Lids Set of 4, Airtight Storage for Spices, Tea and Snacks, Kitchen Counter Organiser", approved: true, usage: { copied: 2, markedUsed: 1, since: isoDaysAgo(10) } },
        { text: "Sample Home Goods Glass Storage Jar Set of 4 with Wooden Style Lids for Kitchen", approved: false, usage: null },
      ],
      FLIPKART: [{ text: "Sample Home Goods Glass Jars with Bamboo Lids, Set of 4", approved: false, usage: { copied: 1, since: isoDaysAgo(10) } }],
      MEESHO: [{ text: "Glass Jar Set of 4 with Bamboo Lid", approved: false, usage: null }],
    },
    bullets: [
      "Borosilicate glass that can be washed without clouding.",
      "Bamboo lids with a seal for spices, tea and snacks.",
      "Clear sides so you can see what is left.",
      "Four jars in one set for a tidy counter.",
      "Hand wash the bamboo lids and keep them dry.",
    ],
    description: "Four clear glass jars with bamboo lids for spices, tea and snacks. The seal keeps contents fresh and the jars look good on an open shelf. This is sample listing text for illustration.",
    backend: "glass jar bamboo lid spice tea storage set",
    tags: ["#GlassJars", "#KitchenDecor", "#SpiceStorage", "#BambooLid"],
  },
  {
    sku: "SHG-LB-1",
    label: "Steel Lunch Box, double wall",
    days: 11,
    titles: {
      AMAZON: [
        { text: "Sample Home Goods Double Wall Steel Lunch Box, Leakproof and Insulated, Keeps Food Warm for Office and School", approved: false, usage: { copied: 1, since: isoDaysAgo(9) } },
        { text: "Sample Home Goods Insulated Steel Tiffin Lunch Box with Leakproof Lid", approved: false, usage: null },
      ],
      FLIPKART: [{ text: "Sample Home Goods Double Wall Steel Lunch Box, Leakproof", approved: false, usage: null }],
      MEESHO: [{ text: "Steel Lunch Box Leakproof Insulated", approved: false, usage: null }],
    },
    bullets: [
      "Double wall steel keeps food warm until lunch.",
      "Leakproof lid for dal, curry and rice.",
      "No plastic smell.",
      "Easy to carry in a bag.",
      "Wash with warm soapy water.",
    ],
    description: "A double wall steel lunch box that keeps food warm and does not leak. Suitable for office and school bags. This is sample listing text for illustration.",
    backend: "steel lunch box insulated leakproof tiffin office school",
    tags: ["#LunchBox", "#SteelTiffin", "#OfficeLunch"],
  },
];

const titleRows = (): ShowcaseTitle[] =>
  PRODUCTS.flatMap((p) =>
    (Object.keys(p.titles) as Marketplace[]).flatMap((mp) =>
      p.titles[mp].map((t, i): ShowcaseTitle => ({
        generationId: `sample-gen-${p.sku}-${mp}`,
        optionId: `sample-opt-${p.sku}-${mp}-${i + 1}`,
        rank: i + 1,
        titleText: t.text,
        charCount: t.text.length,
        maxChars: MAX[mp],
        constraint: SOURCE,
        approved: t.approved ? { approvalId: `sample-approval-${p.sku}-${mp}`, approvedAt: isoDaysAgo(p.days - 1), editedBySeller: false } : null,
        sku: p.sku,
        productLabel: p.label,
        marketplace: mp,
        generatedAt: isoDaysAgo(p.days),
        origin,
        usage: t.usage,
      })),
    ),
  );

const packs = (): CopyPack[] =>
  PRODUCTS.flatMap((p) =>
    (Object.keys(p.titles) as Marketplace[]).map((mp): CopyPack => ({
      generationId: `sample-pack-${p.sku}-${mp}`,
      marketplace: mp,
      sku: p.sku,
      productLabel: p.label,
      groundedOn: { approvalId: p.titles[mp][0].approved ? `sample-approval-${p.sku}-${mp}` : null, titleText: p.titles[mp][0].text, basis: p.titles[mp][0].approved ? "Seller-approved title" : "Top suggested title" },
      bullets: p.bullets.map((text) => ({ text, chars: text.length, max: 250 })),
      description: { text: p.description, chars: p.description.length, max: 2000 },
      backendTerms: mp === "AMAZON" ? { text: p.backend, bytes: p.backend.length, maxBytes: 249 } : null,
      generatedAt: isoDaysAgo(p.days),
      origin,
      labels: p.titles[mp][0].approved ? ["Grounded in the approved title"] : ["Grounded in the top suggested title"],
    })),
  );

const hashtagSets = (): HashtagSet[] =>
  PRODUCTS.map((p) => ({ generationId: `sample-tags-${p.sku}`, sku: p.sku, productLabel: p.label, hashtags: p.tags, generatedAt: isoDaysAgo(p.days), origin }));

const trends = (): TrendReport[] => [
  {
    generationId: "sample-trend-1",
    createdAt: isoDaysAgo(1, 6),
    status: "COMPLETE",
    nicheTerms: ["kitchen storage", "steel containers"],
    sections: [
      {
        name: "Market news",
        state: "OK",
        findings: [
          { text: "Sample note: home-organisation videos keep featuring airtight steel containers.", sourceName: "Sample Home Weekly", sourceUrl: "https://news.example.test/home-weekly/1", publishedAt: isoDaysAgo(3), retrievedAt: isoDaysAgo(1, 6), corroboration: "Two independent sources" },
          { text: "Sample note: sellers discuss packaging that avoids plastic as a selling point.", sourceName: "Sample Seller Forum", sourceUrl: "https://forum.example.test/threads/22", publishedAt: isoDaysAgo(5), retrievedAt: isoDaysAgo(1, 6), corroboration: "Single source" },
        ],
      },
      {
        name: "Seasonal themes",
        state: "OK",
        findings: [{ text: "Sample note: festive-season gifting searches mention kitchen sets.", sourceName: "Sample Trends Digest", sourceUrl: "https://trends.example.test/digest/8", publishedAt: isoDaysAgo(7), retrievedAt: isoDaysAgo(1, 6), corroboration: "Single source" }],
      },
    ],
    interpretationLabel: "Interpretation, not a forecast",
    evidenceRef: "sample-evidence-ref-trend-1",
  },
  {
    generationId: "sample-trend-2",
    createdAt: isoDaysAgo(9, 6),
    status: "COMPLETE",
    nicheTerms: ["lunch boxes"],
    sections: [{ name: "Market news", state: "OK", findings: [{ text: "Sample note: office-lunch content favours leakproof, insulated designs.", sourceName: "Sample Lifestyle Blog", sourceUrl: "https://blog.example.test/lunch/4", publishedAt: null, retrievedAt: isoDaysAgo(9, 6), corroboration: null }] }],
    interpretationLabel: "Interpretation, not a forecast",
    evidenceRef: "sample-evidence-ref-trend-2",
  },
];

const query = (m: RegExpMatchArray) => new URL(m.input ?? "", "http://sample.test").searchParams;

/** The usage event write (`POST .../usage-events`) is a plain fetch, not apiFetch, so sample data never touches it. */
export const cmoRoutes: DemoRoute[] = [
  {
    method: "GET",
    match: /^\/api\/v1\/cmo\/showcase\/products(\?.*)?$/,
    reply: (m): { items: ShowcaseProduct[] } => {
      const q = query(m).get("q")?.toLowerCase();
      return {
        items: PRODUCTS.filter((p) => !q || p.label.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q)).map((p) => ({
          sku: p.sku,
          label: p.label,
          lastGeneratedAt: isoDaysAgo(p.days),
          counts: { AMAZON: p.titles.AMAZON.length, FLIPKART: p.titles.FLIPKART.length, MEESHO: p.titles.MEESHO.length },
        })),
      };
    },
  },
  { method: "GET", match: /^\/api\/v1\/cmo\/showcase\/trends(\?.*)?$/, reply: () => ({ items: trends(), nextCursor: null }) },
  {
    method: "GET",
    match: /^\/api\/v1\/cmo\/showcase\/titles(\?.*)?$/,
    reply: (m): TitlesPage => {
      const p = query(m);
      const mp = (p.get("marketplace") ?? "AMAZON") as Marketplace;
      const sku = p.get("sku");
      const q = p.get("q")?.toLowerCase();
      const approvedOnly = p.get("approvedOnly") === "true";
      let items = titleRows().filter((t) => t.marketplace === mp && (!sku || t.sku === sku) && (!approvedOnly || t.approved) && (!q || t.titleText.toLowerCase().includes(q)));
      if (p.get("view") === "frequent") items = items.filter((t) => t.usage?.copied || t.usage?.markedUsed);
      return { items, usage: { available: true, basis: "RECORDED_EVENTS", since: isoDaysAgo(14) }, nextCursor: null };
    },
  },
  {
    method: "GET",
    match: /^\/api\/v1\/cmo\/showcase\/copy-packs(\?.*)?$/,
    reply: (m): { items: CopyPack[] } => {
      const p = query(m);
      const mp = p.get("marketplace");
      const sku = p.get("sku");
      const q = p.get("q")?.toLowerCase();
      return { items: packs().filter((c) => (!mp || c.marketplace === mp) && (!sku || c.sku === sku) && (!q || c.productLabel.toLowerCase().includes(q) || c.groundedOn.titleText.toLowerCase().includes(q))) };
    },
  },
  {
    method: "GET",
    match: /^\/api\/v1\/cmo\/showcase\/hashtags(\?.*)?$/,
    reply: (m): { items: HashtagSet[] } => {
      const p = query(m);
      const sku = p.get("sku");
      const q = p.get("q")?.toLowerCase();
      return { items: hashtagSets().filter((h) => (!sku || h.sku === sku) && (!q || h.productLabel.toLowerCase().includes(q))) };
    },
  },
  {
    method: "GET",
    match: /^\/api\/v1\/cmo\/showcase\/compliance(\?.*)?$/,
    reply: (): ComplianceSummary => ({
      counts: [
        { label: "Titles within the stored character limit", count: 15, basis: "Stored length check against the verified marketplace limit" },
        { label: "Titles with a stored limit source", count: 15, basis: "Marketplace rules page recorded when the title was made" },
        { label: "Bullets within the stored limit", count: 45, basis: "Stored length check" },
      ],
    }),
  },
];
