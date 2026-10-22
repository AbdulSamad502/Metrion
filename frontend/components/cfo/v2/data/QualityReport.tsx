import type { QualityReport as Report } from "@/lib/cfoV2/ingest";

const ROW_LABELS: Record<string, string> = {
  read: "Rows read",
  posted: "Rows saved",
  failed_validation: "Rows that could not be read",
  duplicate_overlap_with_earlier_uploads: "Already in earlier uploads",
  duplicate_repeats_in_file: "Repeated inside this file",
  held_conflicting: "Held: different values for a known line",
  held_ambiguous: "Held: cannot tell apart from a double export",
  held_total: "Held in total",
  blank_skipped: "Blank rows skipped",
  ragged_padded: "Short rows padded",
};

/** What the file contained and what happened to each row — counts exactly as the server reports them, plus every point that needs the seller. */
export function QualityReport({ report }: { report: Report }) {
  const rows = Object.entries(report.rows ?? {});
  const findings = Object.entries(report.findings_by_rule ?? {});
  const needs = report.needs_seller ?? [];
  return (
    <section aria-label="Data quality report" className="flex flex-col gap-3">
      <h3 className="t-label">What happened to your file</h3>
      <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 t-body">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>{ROW_LABELS[k] ?? k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {findings.length > 0 && (
        <div>
          <div className="t-label">Reasons rows were excluded</div>
          <ul className="list-disc pl-5 t-body">
            {findings.map(([rule, n]) => (
              <li key={rule}>
                {rule}: {n}
              </li>
            ))}
          </ul>
        </div>
      )}
      {needs.length > 0 ? (
        <div role="status">
          <div className="t-label">Needs your attention</div>
          <ul className="list-disc pl-5 t-body">
            {needs.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="t-meta" style={{ color: "var(--text-5)" }}>
          Nothing in this file needs your attention.
        </p>
      )}
      {report.confidence && (
        <p className="t-meta" style={{ color: "var(--text-5)" }}>
          Figures built from this file are {report.confidence.toLowerCase()} until they are checked against more data.
        </p>
      )}
    </section>
  );
}
