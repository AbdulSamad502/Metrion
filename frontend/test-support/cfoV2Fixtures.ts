import type { FigureData } from "@/lib/cfoV2/types";

export const fig = (over: Partial<FigureData> = {}): FigureData => ({
  label: "Contribution Profit",
  valueDisplay: "₹1,23,456.00",
  completeness: "COMPLETE",
  register: "DERIVED",
  source: [{ kind: "ENGINE", label: "Uploaded settlement reports" }],
  lastUpdated: "2026-10-22 09:00",
  asOfDate: "2026-10-22",
  periodCoverage: "2026-09-01 to 2026-09-30",
  engineResultRef: "eng_abc",
  formulaVersion: "cp-3",
  exclusions: [],
  missingInputs: [],
  statusNotes: [],
  ...over,
});
