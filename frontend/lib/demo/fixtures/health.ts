import type { HealthEntry, Presentation, PresentationFigure } from "@/lib/ceo";
import { isoDaysAgo, monthBounds } from "./dates";

/** SAMPLE saved results for the Overview (the Sample-data preview). They follow `GET /api/v1/ceo/state/health` entry for entry (backend/src/backend/ceo/business_state.py):
 * every `value` is a string exactly as the backend formats a figure (`₹4,82,150.00`), and every figure keeps its own register, as-of date and ref. The business and
 * every number are fictional and hand-typed: nothing here is computed, summed or derived from anything. */
const fig = (label: string, value: string, id: string, register: string, asOf: string, note: string | null = null): PresentationFigure => ({
  label, value, register, as_of: asOf, note, ref: { kind: "ENGINE_RESULT", id: `demo-${id}`, as_of: asOf },
});
const present = (headline: string, figures: PresentationFigure[], over: Partial<Presentation> = {}): Presentation => ({
  version: 1, headline, figures, conflicts: [], facts: [], gaps: [], offers: [], artefacts: [], ...over,
});

export function demoHealth(): { entries: HealthEntry[] } {
  const computed = isoDaysAgo(2, 8);
  const { start, end } = monthBounds(1);
  const period = `${start}/${end}`;
  return {
    entries: [
      {
        key: "BS_PNL_LATEST", status: "AVAILABLE", period, asOf: computed, previewHint: null,
        presentation: present("Net realized revenue: ₹6,84,300.00", [
          fig("Net realized revenue", "₹6,84,300.00", "rev", "DERIVED", computed),
          fig("Contribution profit", "₹1,42,860.00", "profit", "VERIFIED", computed, "Calculated by the engine from the reports you uploaded"),
          fig("Marketplace fees", "₹98,420.00", "fees", "DERIVED", computed),
        ]),
      },
      {
        key: "BS_HEALTH_BANDS", status: "AVAILABLE", period, asOf: computed, previewHint: null,
        presentation: present("Contribution margin band: GOOD", [
          fig("Contribution margin band", "GOOD", "band-margin", "DERIVED", computed),
          fig("Fee ratio band", "WATCH", "band-fee", "DERIVED", computed),
          fig("Return rate band", "GOOD", "band-return", "DERIVED", computed),
        ], { facts: [{ label: "Overall health band", text: "WATCH (classified by the engine from the metrics listed)", basis: "SOURCE_DERIVED" }] }),
      },
      {
        key: "BS_LEAK_OPEN", status: "PARTIAL", period: null, asOf: isoDaysAgo(3, 9), previewHint: null,
        presentation: present("Open leak findings", [
          fig("SHORT_SETTLEMENT — AMAZON (SKU SHG-STL-12) [HIGH]", "₹18,640.00", "leak-1", "DERIVED", isoDaysAgo(3, 9)),
          fig("UNRECONCILED_RETURN — FLIPKART (SKU SHG-CNT-07) [MEDIUM]", "₹6,210.00", "leak-2", "DERIVED", isoDaysAgo(5, 9)),
          fig("FEE_OVERCHARGE — MEESHO [LOW]", "₹1,480.00", "leak-3", "DERIVED", isoDaysAgo(9, 9)),
        ], { gaps: ["More open leak findings exist than are listed here."] }),
      },
      {
        key: "BS_DATA_GAPS", status: "AVAILABLE", period: null, asOf: isoDaysAgo(1, 9), previewHint: null,
        presentation: present("Inputs still needed", [], {
          facts: [{ label: "Packaging cost for SKU SHG-STL-12", text: "Needed to compute contribution profit for that product.", basis: "SOURCE_DERIVED" }],
        }),
      },
      {
        key: "BS_SELLER_CONTEXT", status: "AVAILABLE", period: null, asOf: isoDaysAgo(12, 9), previewHint: null,
        presentation: present("Your saved goal and notes", [
          fig("Monthly profit goal", "₹1,50,000.00", "goal", "MANUAL", isoDaysAgo(12, 9), "Entered by you"),
        ]),
      },
      {
        key: "BS_INGEST_STATUS", status: "UNAVAILABLE", period: null, asOf: null,
        previewHint: "No report upload status is saved for this sample business.", presentation: null,
      },
    ],
  };
}
