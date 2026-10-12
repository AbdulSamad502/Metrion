"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ChoiceChips, Field, ProblemNotice, SubmitButton, TextArea, TextInput, useAction } from "@/components/cmo/shared";
import { useCmoSession } from "@/components/cmo/session";
import { cmo, MARKETPLACES, validateIntake, type ImageAnalysis, type ImageUpload } from "@/lib/cmo";

/** Step 1: the product. A photo is optional; everything the seller types is theirs. Image-derived values are only ever
 * SUGGESTIONS until the seller confirms them in their own words (and, separately, until an approved evaluation passes). */
export function CreateTab({ onNext }: { onNext: () => void }) {
  const { intake, setIntake, marketplaces, setMarketplaces } = useCmoSession();
  const problems = validateIntake(intake);
  const problemFor = (f: string) => problems.find((p) => p.field === f)?.message;
  const ready = problems.length === 0 && marketplaces.length > 0;

  return (
    <div className="mt-stack">
      <PhotoSection />
      <Section title="Product details" hint="Only what you type here (and photo hints you confirm) is used. Nothing is guessed.">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Product name">{(id) => <TextInput id={id} value={intake.productName} onChange={(v) => setIntake({ productName: v })} placeholder="e.g. Steel water bottle" maxLength={200} />}</Field>
          <Field label="Brand">{(id) => <TextInput id={id} value={intake.brand} onChange={(v) => setIntake({ brand: v })} placeholder="e.g. AquaKeep" maxLength={200} />}</Field>
          <Field label="SKU" hint="Your own product code. Needed to save facts you confirm from a photo.">{(id) => <TextInput id={id} value={intake.sku} onChange={(v) => setIntake({ sku: v })} maxLength={128} />}</Field>
          <Field label="Category (your words)" hint="Plain words, for example “kitchen” or “water bottles”.">{(id) => <TextInput id={id} value={intake.categoryHint} onChange={(v) => setIntake({ categoryHint: v })} maxLength={200} />}</Field>
          <Field label="Target price (optional, ₹)" hint="Shown back to you only; it is never written into your listing text." error={problemFor("targetPrice")}>
            {(id) => <TextInput id={id} value={intake.targetPriceRupees} onChange={(v) => setIntake({ targetPriceRupees: v })} inputMode="decimal" placeholder="499" invalid={!!problemFor("targetPrice")} />}
          </Field>
        </div>
        <div className="mt-4">
          <AttributeEditor />
        </div>
        <div className="mt-4">
          <Field label="Notes (one per line)" hint="Context for the writer. Notes are not treated as specifications.">{(id) => <TextArea id={id} value={intake.notes} onChange={(v) => setIntake({ notes: v })} rows={3} maxLength={4000} />}</Field>
        </div>
        {problemFor("product") && (
          <div role="status" className="mt-3 t-body-sm" style={{ color: "var(--warning)" }}>
            {problemFor("product")}
          </div>
        )}
      </Section>
      <Section title="Marketplaces" hint="Titles and listing copy are written separately for each one. Nothing is defaulted — choose at least one.">
        <ChoiceChips options={MARKETPLACES} value={marketplaces} onChange={setMarketplaces} label="Marketplaces" />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <SubmitButton primary onClick={onNext} busy={false} label="Continue to titles" busyLabel="" disabled={!ready} title={ready ? undefined : "Add product details and choose a marketplace first"} />
          {!ready && (
            <span className="t-meta" style={{ color: "var(--text-6)" }}>
              {marketplaces.length === 0 ? "Choose at least one marketplace." : "Add product details to continue."}
            </span>
          )}
        </div>
      </Section>
    </div>
  );
}

function AttributeEditor() {
  const { intake, setIntake } = useCmoSession();
  const set = (i: number, patch: Partial<{ name: string; value: string }>) =>
    setIntake({ attributes: intake.attributes.map((a, idx) => (idx === i ? { ...a, ...patch } : a)) });
  return (
    <div>
      <div className="mb-1 t-body-sm" style={{ color: "var(--text-6)" }}>
        Attributes you know for sure (colour, material, size, weight…)
      </div>
      <div className="flex flex-col gap-2">
        {intake.attributes.map((a, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
            <TextInput value={a.name} onChange={(v) => set(i, { name: v })} placeholder="Name, e.g. material" maxLength={100} />
            <TextInput value={a.value} onChange={(v) => set(i, { value: v })} placeholder="Value, e.g. stainless steel" maxLength={500} />
            <button type="button" className="mt-btn mt-btn-secondary mt-focus rounded-lg px-3 py-2 t-meta font-bold" aria-label={`Remove attribute ${i + 1}`} onClick={() => setIntake({ attributes: intake.attributes.filter((_, idx) => idx !== i) })}>
              Remove
            </button>
          </div>
        ))}
        {intake.attributes.length < 50 && (
          <button type="button" className="mt-btn mt-btn-secondary mt-focus min-h-[36px] w-fit rounded-lg px-3 py-1.5 t-meta font-bold sm:min-h-0" onClick={() => setIntake({ attributes: [...intake.attributes, { name: "", value: "" }] })}>
            + Add an attribute
          </button>
        )}
      </div>
    </div>
  );
}

function PhotoSection() {
  const { getToken } = useAuth();
  const { intake, setIntake, record } = useCmoSession();
  const upload = useAction<ImageUpload>();
  const analysis = useAction<ImageAnalysis>();
  const confirm = useAction<{ factId: string; created: boolean }>();
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const doUpload = async () => {
    if (!file) return;
    const r = await upload.run(() => cmo.uploadImage(getToken, file));
    if (r) {
      record("Photo upload", 0);
      analysis.reset();
    }
  };
  const doAnalyze = async () => {
    if (!upload.result) return;
    const r = await analysis.run(() => cmo.analyzeImage(getToken, upload.result!.assetId));
    if (r) {
      record("Photo analysis", 0);
      if (r.state !== "FAILED") setIntake({ imageAnalysisId: r.analysisId });
    }
  };
  const doConfirm = async (name: string, value: string | null) => {
    if (!analysis.result) return;
    const r = await confirm.run(() => cmo.confirmHint(getToken, analysis.result!.analysisId, name, intake.sku.trim(), value));
    if (r) {
      record("Confirmed a photo hint", 0);
      setConfirmed((c) => ({ ...c, [name]: value ?? "" }));
    }
  };

  const a = analysis.result;
  return (
    <Section
      title="Product photo (optional)"
      hint="One clear photo of the product. Metrion reads what is visible, but treats it as a hint you must confirm — it never puts a photo guess in your listing on its own."
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Choose a photo" hint="JPEG, PNG or WebP. Location data and other hidden details are stripped before it is stored.">
          {(id) => <input id={id} type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => { setFile(e.target.files?.[0] ?? null); upload.reset(); analysis.reset(); }} className="t-body-sm min-h-6" />}
        </Field>
        <SubmitButton onClick={doUpload} busy={upload.busy} label="Upload photo" busyLabel="Uploading…" disabled={!file} />
        {upload.result && <SubmitButton onClick={doAnalyze} busy={analysis.busy} label={a ? "Analyse again" : "Read the photo"} busyLabel="Reading the photo…" primary={!a} />}
      </div>
      <div className="mt-3 flex flex-col gap-3">
        <ProblemNotice problem={upload.problem} onRetry={doUpload} />
        <ProblemNotice problem={analysis.problem} onRetry={doAnalyze} />
        {upload.busy && <LoadingState lines={1} label="Uploading photo" />}
        {upload.result && (
          <div className="t-body-sm" style={{ color: "var(--text-4)" }}>
            Photo stored ({upload.result.width}×{upload.result.height}){upload.result.created ? "" : " — you had already uploaded this one"}. No units used.
          </div>
        )}
        {analysis.busy && <LoadingState lines={3} label="Reading the photo" />}
        {a && (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <StatusBadge tone={a.state === "FAILED" ? "negative" : a.state === "COMPLETE" ? "accent" : "warning"}>{a.state === "COMPLETE" ? "Photo read" : a.state === "FAILED" ? "Could not read the photo" : "Partly read"}</StatusBadge>
              {!a.trustGate.open && (
                <StatusBadge tone="warning" title="The photo reader has not passed Metrion’s accuracy check yet, so every value from it is only a suggestion.">
                  Suggestions only — unverified
                </StatusBadge>
              )}
            </div>
            {a.reason && <div className="mb-2 t-body-sm" style={{ color: "var(--text-5)" }}>{a.reason}</div>}
            {a.state === "FAILED" ? (
              <label className="flex items-center gap-2 t-body-sm" style={{ color: "var(--text-4)" }}>
                <input type="checkbox" checked={intake.textOnlyConfirmed} onChange={(e) => setIntake({ textOnlyConfirmed: e.target.checked })} />
                Continue with text only (no photo information will be used)
              </label>
            ) : a.attributes.length === 0 ? (
              <EmptyState compact title="Nothing readable found" description="Add the details yourself in the form below." />
            ) : (
              <ul className="flex flex-col gap-2">
                {a.attributes.map((attr) => {
                  const done = confirmed[attr.name] !== undefined;
                  const draft = drafts[attr.name] ?? attr.value ?? "";
                  return (
                    <li key={attr.name} className="rounded-xl px-3 py-2" style={{ border: "1px solid var(--border-hover)" }}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{attr.name}</span>
                        <StatusBadge tone={attr.trustState === "EVAL_PASSED" ? "accent" : "warning"}>{attr.trustState === "EVAL_PASSED" ? "Photo reading verified" : "Unverified hint"}</StatusBadge>
                        {done && <StatusBadge tone="accent">You confirmed this</StatusBadge>}
                      </div>
                      {attr.value === null ? (
                        <div className="mt-1 t-body-sm" style={{ color: "var(--text-6)" }}>Not visible in the photo.</div>
                      ) : (
                        <div className="mt-2 flex flex-wrap items-end gap-2">
                          <div className="min-w-[14rem] flex-1">
                            <TextInput value={draft} onChange={(v) => setDrafts((d) => ({ ...d, [attr.name]: v }))} maxLength={500} />
                          </div>
                          <SubmitButton onClick={() => doConfirm(attr.name, draft.trim() || null)} busy={confirm.busy} label={done ? "Confirm again" : "This is correct — use it"} busyLabel="Saving…" disabled={!intake.sku.trim() || !draft.trim()} title={intake.sku.trim() ? undefined : "Enter your SKU below first"} />
                        </div>
                      )}
                      {attr.note && <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{attr.note}</div>}
                    </li>
                  );
                })}
              </ul>
            )}
            <ProblemNotice problem={confirm.problem} />
          </div>
        )}
      </div>
    </Section>
  );
}
