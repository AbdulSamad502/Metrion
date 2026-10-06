"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CopyButton, ProblemNotice, RecommendOnlyNote, SubmitButton, TextInput, Unit, useAction, when } from "@/components/cmo/shared";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, marketplaceLabel, validateIntake, type Marketplace, type RunResponse, type TitleSetArtefact } from "@/lib/cmo";

/** Step 2: five-ish title options per marketplace (the exact count is the marketplace rule on file), then the seller approves one —
 * or edits it. Approving costs nothing. Option order is presentation order, never a quality ranking. */
export function TitlesTab({ onNext }: { onNext: () => void }) {
  const { getToken } = useAuth();
  const s = useCmoSession();
  const gen = useAction<RunResponse<TitleSetArtefact>>();
  const blockers = [...validateIntake(s.intake).map((p) => p.message), ...(s.marketplaces.length === 0 ? ["Choose at least one marketplace on the Product tab."] : [])];

  const generate = async (renew: boolean) => {
    if (blockers.length) return;
    if (renew) s.renewKey("titles");
    const r = await gen.run(() => cmo.titleSets(getToken, s.intake, s.keyFor("titles"), s.marketplaces));
    if (r) {
      s.setTitleSets(r.artefacts);
      s.record("Title options", r.unitsBilled);
    }
  };
  const sets = s.marketplaces.map((m) => s.titleSets[m]).filter((x): x is TitleSetArtefact => !!x);

  return (
    <div className="mt-stack">
      <Section
        title="Title options"
        hint="One set per marketplace, written for that marketplace’s rules. You choose; Metrion never picks for you."
        action={
          <SubmitButton primary onClick={() => generate(sets.length > 0)} busy={gen.busy} label={sets.length ? "Write new options" : "Write title options"} busyLabel="Writing titles…" disabled={blockers.length > 0} title={blockers[0]} />
        }
      >
        {blockers.length > 0 && (
          <div role="status" className="mb-3 t-body-sm" style={{ color: "var(--warning)" }}>
            {blockers[0]}
          </div>
        )}
        <ProblemNotice problem={gen.problem} onRetry={() => generate(false)} />
        {gen.busy && <LoadingState lines={4} label="Writing titles for each marketplace" />}
        {gen.result && !gen.busy && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Unit n={gen.result.unitsBilled} what="title request" />
            <span className="t-meta" style={{ color: "var(--text-6)" }}>
              A marketplace that could not be written is not charged.
            </span>
          </div>
        )}
        {!gen.busy && sets.length === 0 && !gen.problem && <EmptyState icon="marketing" title="No titles yet" description="Write title options to see them here, one set for each marketplace you chose." />}
      </Section>

      {sets.map((set) => (
        <MarketplaceTitles key={set.id} set={set} />
      ))}

      {Object.keys(s.approvals).length > 0 && (
        <div>
          <SubmitButton primary onClick={onNext} busy={false} label="Continue to listing copy" busyLabel="" />
        </div>
      )}
    </div>
  );
}

function MarketplaceTitles({ set }: { set: TitleSetArtefact }) {
  const { getToken } = useAuth();
  const { approvals, setApproval, record } = useCmoSession();
  const m = set.marketplace as Marketplace;
  const approval = approvals[m];
  const [picked, setPicked] = useState<string | null>(null);
  const [edit, setEdit] = useState("");
  const approve = useAction<unknown>();

  const doApprove = async (opts: { optionId?: string; editedText?: string }) => {
    const r = await approve.run(() => cmo.approveTitle(getToken, set.id, opts));
    if (r && typeof r === "object" && "approvalId" in r) {
      const a = r as { approvalId: string; generationId: string; approvedText: string; editedBySeller: boolean };
      setApproval(m, { approvalId: a.approvalId, generationId: a.generationId, approvedText: a.approvedText, editedBySeller: a.editedBySeller });
      record("Approved a title", 0);
    }
  };

  return (
    <Section
      title={marketplaceLabel(m)}
      hint={set.constraint?.sourceUrl ? <>Rules used: <a className="underline" href={set.constraint.sourceUrl} target="_blank" rel="noreferrer">marketplace guide</a>, checked {when(set.constraint.verifiedAt)}.</> : undefined}
      action={approval ? <StatusBadge tone="accent" dot>Approved by you</StatusBadge> : undefined}
    >
      {set.status === "FAILED" ? (
        <FailureNote set={set} />
      ) : (
        <div className="flex flex-col gap-3">
          {set.short && (
            <StatusBadge tone="warning" title="Fewer options than usual — we only show titles that follow the rules and your facts.">
              {set.shortLabel ?? `Only ${set.deliveredOptionCount ?? set.options?.length} of ${set.expectedOptionCount} options could be written`}
            </StatusBadge>
          )}
          <div role="radiogroup" aria-label={`${marketplaceLabel(m)} title options`} className="flex flex-col gap-2">
            {(set.options ?? []).map((o) => (
              <label key={o.id} className="flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5" style={{ border: `1px solid ${picked === o.id ? "var(--accent-border-subtle)" : "var(--border-hover)"}` }}>
                <input type="radio" name={`title-${set.id}`} checked={picked === o.id} onChange={() => { setPicked(o.id); setEdit(o.text); }} className="mt-1" />
                <span className="min-w-0 flex-1">
                  <span className="block t-body" style={{ color: "var(--text-2)" }}>{o.text}</span>
                  <span className="t-meta" style={{ color: "var(--text-6)" }}>Option {o.rank} · {o.charCount} characters</span>
                </span>
                <CopyButton text={o.text} />
              </label>
            ))}
          </div>
          <div className="t-meta" style={{ color: "var(--text-6)" }}>The order is just the order they were written in — it does not say one is better.</div>
          {picked && (
            <div className="flex flex-col gap-2">
              <label className="t-body-sm" style={{ color: "var(--text-6)" }} htmlFor={`edit-${set.id}`}>Edit before approving (optional)</label>
              <TextInput id={`edit-${set.id}`} value={edit} onChange={setEdit} maxLength={500} />
              <div className="flex flex-wrap gap-2">
                <SubmitButton primary busy={approve.busy} busyLabel="Approving…" label="Approve this title" onClick={() => doApprove(edit.trim() && edit.trim() !== set.options?.find((o) => o.id === picked)?.text ? { editedText: edit.trim() } : { optionId: picked })} />
              </div>
              <div className="t-meta" style={{ color: "var(--text-6)" }}>Approving is free. If you change the text it must still follow this marketplace’s title rules.</div>
            </div>
          )}
          <ProblemNotice problem={approve.problem} />
          {approval && (
            <div className="rounded-xl px-3 py-2.5" style={{ background: "var(--accent-fill-default)" }}>
              <div className="t-meta font-bold" style={{ color: "var(--accent)" }}>Your approved title{approval.editedBySeller ? " (edited by you)" : ""}</div>
              <div className="mt-1 t-body" style={{ color: "var(--text-2)" }}>{approval.approvedText}</div>
            </div>
          )}
          <RecommendOnlyNote />
        </div>
      )}
    </Section>
  );
}

export function FailureNote({ set }: { set: { failure?: { code: string; reason: string | null; missingFacts: string[] } } }) {
  const f = set.failure;
  return (
    <div className="flex flex-col gap-2">
      <StatusBadge tone="negative">Not written — you were not charged</StatusBadge>
      <div className="t-body-sm" style={{ color: "var(--text-3)" }}>{f?.reason ?? "This could not be written right now."}</div>
      {f && f.missingFacts.length > 0 && (
        <div className="t-body-sm" style={{ color: "var(--text-4)" }}>
          To write it, add: {f.missingFacts.join(", ")}.
        </div>
      )}
      {f?.code === "CONSTRAINT_BLOCKED" || f?.code?.startsWith("CONSTRAINT") ? (
        <div className="t-meta" style={{ color: "var(--text-6)" }}>This marketplace’s listing rules are not set up yet, so nothing is written for it. Other marketplaces are not affected.</div>
      ) : null}
    </div>
  );
}
