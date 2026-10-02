import { EvidenceStateBadge, type EvidenceState } from "@/components/ui/EvidenceStateBadge";

export type FlowStep = { name: string; detail: string };

export const CI_STEPS: FlowStep[] = [
  { name: "Discover", detail: "Find competing listings, or add a URL you already know." },
  { name: "Observe", detail: "Submit a screenshot or type in what you see. URLs are never fetched." },
  { name: "Evaluate", detail: "Compare against your own price, margin and listing." },
  { name: "Confirm", detail: "Check AI-read values against the listing before you rely on them." },
  { name: "Act", detail: "You decide. Metrion recommends only and never edits a marketplace." },
];

/** How a competitor fact travels from first sight to a decision. A map of the real workflow, not a
 * progress tracker: it does not know which step you are on, only what each step means. */
export function PipelineStepper({ steps = CI_STEPS, label = "Competitor intelligence workflow" }: { steps?: FlowStep[]; label?: string }) {
  return (
    <ol className="m-0 grid list-none grid-cols-1 gap-x-6 gap-y-4 p-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" aria-label={label}>
      {steps.map((s, i) => (
        <li key={s.name} className="flex gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full t-micro font-bold"
            style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
          >
            {i + 1}
          </span>
          <span className="min-w-0">
            <span className="block t-body font-semibold" style={{ color: "var(--text-2)" }}>
              {s.name}
            </span>
            <span className="block t-body-sm leading-snug" style={{ color: "var(--text-5)" }}>
              {s.detail}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

const LEGEND: { state: EvidenceState; meaning: string }[] = [
  { state: "OBSERVED", meaning: "Recorded directly from a source" },
  { state: "INFERRED", meaning: "Derived from other values" },
  { state: "NEEDS_REVIEW", meaning: "Read by an AI model — not verified" },
  { state: "CONFIRMED", meaning: "Entered or confirmed by you" },
];

/** The four evidence states, once, so every badge on the page is self-explanatory. */
export function EvidenceLegend() {
  return (
    <dl className="m-0 flex flex-wrap items-center gap-x-6 gap-y-2" aria-label="Evidence states">
      {LEGEND.map((l) => (
        <div key={l.state} className="flex items-center gap-2">
          <dt>
            <EvidenceStateBadge state={l.state} />
          </dt>
          <dd className="m-0 t-body-sm" style={{ color: "var(--text-5)" }}>
            {l.meaning}
          </dd>
        </div>
      ))}
    </dl>
  );
}
