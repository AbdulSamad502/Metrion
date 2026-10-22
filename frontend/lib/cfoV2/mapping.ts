import { ApiError } from "@/lib/api";

/** Column-mapping contracts (backend `cfo_ingestion.mapping_view` and `ConfirmMappingBody`). */
export type MappingIssue = { rule: string; message: string };
export type MappingFieldEvidence = {
  errors?: MappingIssue[];
  warnings?: MappingIssue[];
  confirm_reasons?: string[];
  detected_tax_inclusion?: string | null;
  enum_values?: string[];
  exact_register_match?: boolean;
};
export type MappingField = {
  index: number;
  sourceColumn: string;
  canonicalField: string | null;
  componentCode: string | null;
  transform: string | null;
  taxInclusion: string | null;
  signConvention: string | null;
  decision: string;
  evidence: MappingFieldEvidence | null;
};
export type MappingView = { mappingId: string; status: string; version: number; reportKind: string; proposedBy: string; verified: boolean; fields: MappingField[] };

export type FieldEdit = { tax_inclusion?: string; sign_convention?: string };
export type ConfirmBody = { decisions: Record<string, string>; overrides: Record<string, FieldEdit> };

export const TAX_CHOICES = [
  { value: "INCLUSIVE", label: "Includes GST" },
  { value: "EXCLUSIVE", label: "Excludes GST" },
] as const;

/** The server's refusal of a mapping: a short message and the list of reasons (nothing was changed). */
export function refusalReasons(e: unknown): string[] | null {
  if (!(e instanceof ApiError) || e.status !== 422) return null;
  const d = e.detail as { reasons?: unknown } | null;
  return d && Array.isArray(d.reasons) ? d.reasons.filter((r): r is string => typeof r === "string") : null;
}

/** A field needs the seller's explicit say when the validator attached confirm reasons — silence is never confirmation. */
export const needsDecision = (f: MappingField): boolean => (f.evidence?.confirm_reasons?.length ?? 0) > 0;
export const hasError = (f: MappingField): boolean => (f.evidence?.errors?.length ?? 0) > 0;
