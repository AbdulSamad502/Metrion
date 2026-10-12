import { registerView } from "@/lib/ceoModel";

export type Register = "VERIFIED" | "DERIVED" | "MANUAL" | "ESTIMATE" | "UNAVAILABLE";

const MEANING: Record<Register, string> = {
  VERIFIED: "Read directly from your uploaded data.",
  DERIVED: "Calculated by Metrion from verified figures.",
  MANUAL: "Entered by you, not checked against a report.",
  ESTIMATE: "Estimated: not a measured figure.",
  UNAVAILABLE: "Not available: a required input is missing.",
};

/** One glyph per register, so the meaning never rests on colour alone. */
function Glyph({ register }: { register: string }) {
  const common = { width: 11, height: 11, viewBox: "0 0 12 12", fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (register === "VERIFIED") return <svg {...common}><path d="M2.5 6.4 5 8.8 9.6 3.6" /></svg>;
  if (register === "DERIVED") return <svg {...common}><path d="M2.5 4.2h7M2.5 7.8h7" /></svg>;
  if (register === "MANUAL") return <svg {...common}><path d="M2.5 9.5 3 7.2l4.8-4.8 1.8 1.8L4.8 9 2.5 9.5Z" /></svg>;
  if (register === "ESTIMATE") return <svg {...common}><path d="M2 7.5c1.4-2.6 2.6-2.6 4 0s2.6 2.6 4 0" /></svg>;
  return <svg {...common}><path d="M3 6h6" /></svg>;
}

/** The provenance chip for a figure: VERIFIED, DERIVED, MANUAL, ESTIMATE or UNAVAILABLE (the five registers of cfo-agent.md 7.4.7, never a sixth).
 * Shape, border style and a glyph carry the distinction as well as colour; the text is the backend's wording from `registerView`, and the title explains it.
 * Any new page that shows a figure uses this, so every number looks like it came from the same system. */
export function ProvenanceBadge({ register }: { register: string }) {
  const view = registerView(register);
  const known = register in MEANING;
  return (
    <span className="mt-prov" data-register={known ? register : "UNAVAILABLE"} title={known ? MEANING[register as Register] : undefined}>
      <Glyph register={register} />
      {view.label}
    </span>
  );
}
