"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { CopyResult } from "@/components/cmo/CopyTab";
import { Field, ProblemNotice, SelectInput, SubmitButton, TextInput, useAction } from "@/components/cmo/shared";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, marketplaceLabel, MARKETPLACES, validateIntake, type CopyArtefact, type Marketplace, type RunResponse } from "@/lib/cmo";

type Kind = "description" | "bullets" | "keywords" | "backend-terms" | "hashtags";
const KINDS: { value: Kind; label: string; amazonOnly?: boolean; needsAnchor: boolean }[] = [
  { value: "description", label: "Description only", needsAnchor: true },
  { value: "bullets", label: "Bullet points only", needsAnchor: true },
  { value: "keywords", label: "Keywords only", needsAnchor: true },
  { value: "backend-terms", label: "Amazon backend search terms", amazonOnly: true, needsAnchor: true },
  { value: "hashtags", label: "Hashtag ideas (social posts, not a listing field)", needsAnchor: false },
];

/** One piece at a time, for sellers who already have a title they like — or who want just hashtags. Each piece is one unit. */
export function StandaloneTab() {
  const { getToken } = useAuth();
  const s = useCmoSession();
  const [kind, setKind] = useState<Kind>("description");
  const [marketplace, setMarketplace] = useState<Marketplace>(s.marketplaces[0] ?? "AMAZON");
  const [ownTitle, setOwnTitle] = useState("");
  const gen = useAction<RunResponse<CopyArtefact>>();

  const meta = KINDS.find((k) => k.value === kind)!;
  const approval = s.approvals[marketplace];
  const fromApproval = !!approval && !ownTitle.trim();
  const blockers: string[] = [
    ...validateIntake(s.intake).map((p) => p.message),
    ...(meta.amazonOnly && marketplace !== "AMAZON" ? ["Backend search terms exist only for Amazon."] : []),
    ...(meta.needsAnchor && !fromApproval && !ownTitle.trim() ? ["Approve a title for this marketplace, or paste a title you already use."] : []),
  ];
  const slot = `standalone-${kind}-${marketplace}`;

  const run = async () => {
    if (blockers.length) return;
    const r = await gen.run(() =>
      kind === "hashtags"
        ? cmo.hashtags(getToken, s.intake, s.keyFor(slot), marketplace)
        : cmo.component(getToken, kind, s.intake, s.keyFor(slot), marketplace, fromApproval ? { approvalId: approval!.approvalId } : { sellerTitle: ownTitle.trim() }),
    );
    if (r) s.record(`${meta.label} · ${marketplaceLabel(marketplace)}`, r.unitsBilled);
  };

  return (
    <div className="mt-stack">
      <Section title="Write one piece" hint="Each piece costs one unit, only when it is written successfully.">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="What to write">{(id) => <SelectInput id={id} value={kind} onChange={(v) => { setKind(v as Kind); gen.reset(); }} options={KINDS.map((k) => ({ value: k.value, label: k.label }))} />}</Field>
          <Field label="Marketplace">{(id) => <SelectInput id={id} value={marketplace} onChange={(v) => { setMarketplace(v as Marketplace); gen.reset(); }} options={MARKETPLACES.map((m) => ({ value: m.id, label: m.label }))} />}</Field>
        </div>
        {meta.needsAnchor && (
          <div className="mt-3">
            <Field
              label="A title to write from"
              hint={approval ? `Leave blank to use your approved ${marketplaceLabel(marketplace)} title: “${approval.approvedText}”.` : "Paste the title you already use on this marketplace."}
            >
              {(id) => <TextInput id={id} value={ownTitle} onChange={(v) => { setOwnTitle(v); }} maxLength={500} />}
            </Field>
          </div>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <SubmitButton primary onClick={run} busy={gen.busy} label="Write it" busyLabel="Writing…" disabled={blockers.length > 0} title={blockers[0]} />
          {blockers[0] && <span className="t-meta" style={{ color: "var(--warning)" }}>{blockers[0]}</span>}
        </div>
      </Section>
      <ProblemNotice problem={gen.problem} onRetry={run} />
      {gen.busy && <LoadingState lines={4} label="Writing" />}
      {gen.result && !gen.busy && gen.result.artefacts.map((a) => (
        <Section key={a.id} title={`${meta.label} · ${marketplaceLabel(marketplace)}`}>
          <CopyResult artefact={a} units={gen.result?.unitsBilled ?? 0} />
        </Section>
      ))}
    </div>
  );
}
