"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CopyButton, ProblemNotice, RecommendOnlyNote, SubmitButton, Unit, useAction, when } from "@/components/cmo/shared";
import { FailureNote } from "@/components/cmo/TitlesTab";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, marketplaceLabel, type CopyArtefact, type Marketplace, type RunResponse } from "@/lib/cmo";

/** Step 3: the listing copy pack (description, bullets, keywords) for each marketplace whose title you approved — written from
 * that approved title and that marketplace’s own rules. Nothing is copied from another marketplace’s pack. */
export function CopyTab() {
  const { approvals, marketplaces } = useCmoSession();
  const approved = marketplaces.filter((m) => approvals[m]);
  if (approved.length === 0) {
    return (
      <EmptyState
        icon="marketing"
        title="Approve a title first"
        description="Listing copy is written from a title you approved for that marketplace. Approve one on the Titles tab — or write standalone pieces from a title you already use."
      />
    );
  }
  return (
    <div className="mt-stack">
      {approved.map((m) => (
        <PackSection key={m} marketplace={m} />
      ))}
    </div>
  );
}

function PackSection({ marketplace }: { marketplace: Marketplace }) {
  const { getToken } = useAuth();
  const s = useCmoSession();
  const approval = s.approvals[marketplace]!;
  const slot = `copy-${marketplace}`;
  const gen = useAction<RunResponse<CopyArtefact>>();

  const generate = async (renew: boolean) => {
    if (renew) s.renewKey(slot);
    const r = await gen.run(() => cmo.listingCopy(getToken, s.intake, s.keyFor(slot), marketplace, { approvalId: approval.approvalId }));
    if (r) s.record(`Listing copy · ${marketplaceLabel(marketplace)}`, r.unitsBilled);
  };
  const art = gen.result?.artefacts[0];

  return (
    <Section
      title={marketplaceLabel(marketplace)}
      hint={<>Written from your approved title: “{approval.approvedText}”</>}
      action={<SubmitButton primary={!art} onClick={() => generate(!!art)} busy={gen.busy} label={art ? "Write a fresh version" : "Write listing copy"} busyLabel="Writing…" />}
    >
      <ProblemNotice problem={gen.problem} onRetry={() => generate(false)} />
      {gen.busy && <LoadingState lines={5} label={`Writing ${marketplaceLabel(marketplace)} listing copy`} />}
      {!gen.busy && !art && !gen.problem && <EmptyState compact icon="marketing" title="Not written yet" description="One pack costs one unit, and only if it is written successfully." />}
      {art && !gen.busy && <CopyResult artefact={art} units={gen.result?.unitsBilled ?? 0} />}
    </Section>
  );
}

export function CopyResult({ artefact: a, units }: { artefact: CopyArtefact; units: number }) {
  const [open, setOpen] = useState(false);
  if (a.status === "FAILED") return <FailureNote set={a} />;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone="accent">Ready to copy</StatusBadge>
        <Unit n={units} what="request" />
        {a.reused && <StatusBadge tone="neutral" title="You asked for this before, so nothing new was written or charged.">Shown again — no charge</StatusBadge>}
      </div>
      {a.structuredFields && a.structuredFields.state !== "NOT_REQUIRED" && (
        <div className="rounded-xl px-3 py-2 t-body-sm" style={{ background: "var(--warning-fill)", color: "var(--text-2)" }}>
          This marketplace also asks for structured fields ({a.structuredFields.fields.join(", ") || "see the marketplace form"}). {a.structuredFields.reason ?? "You will need to fill those in yourself."}
        </div>
      )}
      {a.description != null && <Block title={a.descriptionType === "html" ? "Description (HTML allowed)" : "Description"} text={a.description} />}
      {a.bullets && a.bullets.length > 0 && <ListBlock title="Bullet points" items={a.bullets} />}
      {a.keywords && a.keywords.length > 0 && <ListBlock title="Keywords" items={a.keywords} inline />}
      {a.terms && a.terms.length > 0 && (
        <div>
          <Block title="Backend search terms (Amazon, not shown to shoppers)" text={a.joined ?? a.terms.join(" ")} />
          {a.byteCount != null && a.maxBytes != null && (
            <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>
              Uses {a.byteCount} of {a.maxBytes} allowed bytes.
            </div>
          )}
        </div>
      )}
      {a.hashtags && a.hashtags.length > 0 && (
        <div>
          <ListBlock title="Hashtag ideas" items={a.hashtags} inline />
          <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{a.label ?? "Marketing suggestions for social posts — not a listing field."}</div>
        </div>
      )}
      <div>
        <button type="button" className="t-meta underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Hide" : "Show"} the rules this was checked against
        </button>
        {open && (
          <div className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>
            {a.constraint?.sourceUrl ? <>Marketplace guide: <a className="underline" href={a.constraint.sourceUrl} target="_blank" rel="noreferrer">source</a>, checked {when(a.constraint.verifiedAt)}. </> : "No marketplace rule applies to this item. "}
            {a.countRule ? `Characters counted by: ${a.countRule}. ` : ""}
            {a.unverifiedLimits && a.unverifiedLimits.length > 0 ? `Not checked (no verified rule on file): ${a.unverifiedLimits.join(", ")}.` : ""}
          </div>
        )}
      </div>
      <RecommendOnlyNote />
    </div>
  );
}

function Block({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="t-body-sm font-bold" style={{ color: "var(--text-3)" }}>{title}</div>
        <CopyButton text={text} />
      </div>
      <p className="whitespace-pre-wrap rounded-xl px-3 py-2.5 t-body" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>{text}</p>
    </div>
  );
}

function ListBlock({ title, items, inline = false }: { title: string; items: string[]; inline?: boolean }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="t-body-sm font-bold" style={{ color: "var(--text-3)" }}>{title}</div>
        <CopyButton text={items.join(inline ? ", " : "\n")} label="Copy all" />
      </div>
      <ul className={inline ? "flex flex-wrap gap-2" : "flex flex-col gap-1.5"}>
        {items.map((it, i) => (
          <li key={`${i}-${it}`} className={inline ? "rounded-lg px-2.5 py-1 t-body-sm" : "flex items-start justify-between gap-2 rounded-xl px-3 py-2 t-body"} style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
            <span>{it}</span>
            {!inline && <CopyButton text={it} />}
          </li>
        ))}
      </ul>
    </div>
  );
}
