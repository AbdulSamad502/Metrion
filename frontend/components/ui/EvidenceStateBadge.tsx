import { StatusBadge, type Tone } from "./StatusBadge";

/** How far a displayed fact can be trusted — shown wherever a CI/PI value could be mistaken for a
 * verified fact. Deliberately independent of the backend's HIGH/MEDIUM/LOW extraction scale: that
 * scale currently labels every vision-extracted price HIGH (spec open question Q18), so the UI
 * derives the state from PROVENANCE instead and never shows an AI-read value as confirmed.
 *
 *  OBSERVED      recorded straight from a source, no model interpretation (counts, timestamps)
 *  INFERRED      computed or derived from other values
 *  NEEDS_REVIEW  read by an AI model from a screenshot and not yet confirmed by the seller
 *  CONFIRMED     entered or confirmed by the seller
 */
export type EvidenceState = "OBSERVED" | "INFERRED" | "NEEDS_REVIEW" | "CONFIRMED";

const META: Record<EvidenceState, { label: string; tone: Tone; title: string }> = {
  OBSERVED: { label: "Observed", tone: "neutral", title: "Recorded directly from a source, with no model interpretation." },
  INFERRED: { label: "Inferred", tone: "info", title: "Computed or derived from other values." },
  NEEDS_REVIEW: {
    label: "Needs review",
    tone: "warning",
    title: "Read by an AI model from a screenshot. Not confirmed — check it against the listing before relying on it.",
  },
  CONFIRMED: { label: "Confirmed", tone: "accent", title: "Entered or confirmed by you." },
};

/** Maps the backend's per-field provenance tier (competitor_snapshot_field.source / snapshot.confidence). */
export function evidenceStateForTier(tier: string | null | undefined): EvidenceState | null {
  switch (tier) {
    case "SELLER_ENTERED":
      return "CONFIRMED";
    case "VISION_EXTRACTED":
      return "NEEDS_REVIEW";
    case "DERIVED":
      return "INFERRED";
    default:
      return null; // UNAVAILABLE / unknown: no badge — the missing value speaks for itself
  }
}

export function EvidenceStateBadge({ state }: { state: EvidenceState }) {
  const m = META[state];
  return (
    <StatusBadge tone={m.tone} dot title={m.title}>
      {m.label}
    </StatusBadge>
  );
}
