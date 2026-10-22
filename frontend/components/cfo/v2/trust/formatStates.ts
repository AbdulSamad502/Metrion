import type { Tone } from "@/components/ui/StatusBadge";
import type { Completeness } from "@/lib/cfoV2/types";

/** How each completeness state is worded and toned. Text always accompanies the tone (never colour alone), and only COMPLETE is drawn as a confirmed actual. */
export const COMPLETENESS_VIEW: Record<Completeness, { label: string; tone: Tone; meaning: string }> = {
  COMPLETE: { label: "Complete", tone: "accent", meaning: "Every input this figure needs was present." },
  PARTIAL: { label: "Partial", tone: "warning", meaning: "Some inputs or marketplaces are missing; the figure covers only part of the picture." },
  PROVISIONAL: { label: "Provisional", tone: "warning", meaning: "Based on the data so far; it can change as classifications or reports arrive." },
  ESTIMATED: { label: "Estimated", tone: "info", meaning: "An estimate from history, not a measured actual." },
  UNAVAILABLE: { label: "Not available", tone: "neutral", meaning: "A required input is missing, so no figure is shown." },
};

export const isConfirmedActual = (c: Completeness): boolean => c === "COMPLETE";

export const AD_STATUS_TEXT: Record<string, string> = {
  VERIFIED_ZERO: "Advertising: you confirmed no advertising",
  KNOWN_SPEND: "Advertising: spend known",
  MISSING_COVERAGE: "Advertising: the data does not cover the whole period",
  UNKNOWN: "Advertising: no report or cost for this period",
};
