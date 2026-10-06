"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import { ChoiceChips, ProblemNotice, SubmitButton, Unit, useAction } from "@/components/cmo/shared";
import { FailureNote } from "@/components/cmo/TitlesTab";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, marketplaceLabel, validateIntake, type CatalogArtefact, type CatalogAttributeAnswer, type RunResponse } from "@/lib/cmo";

const QUESTIONS = [
  { id: "CATEGORY", label: "Category" }, { id: "VERTICAL", label: "Vertical" }, { id: "COLOR", label: "Colour" }, { id: "MATERIAL", label: "Material" },
  { id: "SIZE", label: "Size" }, { id: "WEIGHT", label: "Weight" }, { id: "DIMENSIONS", label: "Dimensions" }, { id: "BRAND", label: "Brand" },
] as const;

const BASIS: Record<CatalogAttributeAnswer["basis"], { label: string; tone: Tone; meaning: string }> = {
  SELLER_PROVIDED: { label: "You told us", tone: "accent", meaning: "This came from what you entered or confirmed. It can go in your listing." },
  IMAGE_OBSERVED: { label: "Read from your photo", tone: "info", meaning: "The photo reader saw this and its accuracy check passed." },
  SOURCE_DERIVED: { label: "From a cited source", tone: "info", meaning: "This comes from a source we can link to." },
  ESTIMATED: { label: "Estimate — confirm before listing", tone: "warning", meaning: "A rough guess, not a specification. Do not put it in a listing until you confirm it." },
  UNKNOWN: { label: "Unknown", tone: "neutral", meaning: "Metrion does not know this and will not guess. Tell us if you know it." },
};

/** “What colour / weight / category is this?” Every answer says where it came from; estimates and unknowns are never shown as fact. */
export function CatalogTab() {
  const { getToken } = useAuth();
  const s = useCmoSession();
  const [questions, setQuestions] = useState<string[]>(["CATEGORY", "COLOR", "MATERIAL"]);
  const gen = useAction<RunResponse<CatalogArtefact>>();
  const problems = validateIntake(s.intake);

  const ask = async () => {
    if (problems.length || questions.length === 0) return;
    const r = await gen.run(() => cmo.catalog(getToken, s.intake, s.keyFor("catalog"), questions, s.marketplaces));
    if (r) s.record("Catalog answers", r.unitsBilled);
  };

  return (
    <div className="mt-stack">
      <Section title="Ask about this product" hint="Answers come only from what you entered, confirmed photo facts and cited sources. One unit per marketplace answered.">
        <ChoiceChips options={QUESTIONS.map((q) => ({ id: q.id, label: q.label }))} value={questions} onChange={setQuestions} label="Questions" />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <SubmitButton primary onClick={ask} busy={gen.busy} label="Get answers" busyLabel="Looking…" disabled={problems.length > 0 || questions.length === 0} title={problems[0]?.message} />
          {problems[0] && <span className="t-meta" style={{ color: "var(--warning)" }}>{problems[0].message}</span>}
        </div>
      </Section>
      <ProblemNotice problem={gen.problem} onRetry={ask} />
      {gen.busy && <LoadingState lines={4} label="Looking up answers" />}
      {!gen.busy && !gen.result && !gen.problem && <EmptyState icon="marketing" title="No answers yet" description="Choose your questions and press “Get answers”." />}
      {gen.result?.artefacts.map((a) => (
        <Section key={a.id} title={a.marketplace ? marketplaceLabel(a.marketplace) : "This product"} action={<Unit n={a.status === "COMPLETE" && !a.reused ? 1 : 0} what="answer" />}>
          {a.status === "FAILED" ? <FailureNote set={a} /> : (
            <div className="flex flex-col gap-3">
              <ul className="flex flex-col gap-2">
                {(a.attributes ?? []).map((x) => {
                  const b = BASIS[x.basis];
                  return (
                    <li key={x.attribute} className="rounded-xl px-3 py-2.5" style={{ border: "1px solid var(--border-hover)" }}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{x.attribute.charAt(0) + x.attribute.slice(1).toLowerCase()}</span>
                        <StatusBadge tone={b.tone} title={b.meaning}>{b.label}</StatusBadge>
                        {x.requiresSellerInput && <StatusBadge tone="warning">Needs your input</StatusBadge>}
                      </div>
                      <div className="mt-1 t-body" style={{ color: x.value ? "var(--text-2)" : "var(--text-6)" }}>{x.value ?? "—"}</div>
                      {x.estimate && <div className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>Estimate: {JSON.stringify(x.estimate)}</div>}
                      {x.suggestion?.text && <div className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>{x.suggestion.text}</div>}
                      {x.note && <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{x.note}</div>}
                    </li>
                  );
                })}
              </ul>
              {a.disclaimer && <div className="t-meta" style={{ color: "var(--text-6)" }}>{a.disclaimer}</div>}
            </div>
          )}
        </Section>
      ))}
    </div>
  );
}
