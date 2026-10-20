"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { ProfileField } from "@/components/profile/ProfileField";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { EMPTY_FORM, STEPS, fieldError, formErrors, toBody, type BusinessProfileForm, type BusinessProfileResponse } from "@/lib/businessProfile";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** The first-run flow: one short question per slide. Nothing can be skipped — "Next" is refused while the current answer is blank or invalid, and the last slide saves
 * all eight answers in one request (the server re-checks every field). Used inside the onboarding card. */
export function BusinessProfileSteps({ onSaved }: { onSaved: () => void }) {
  const { getToken } = useAuth();
  const [form, setForm] = useState<BusinessProfileForm>(EMPTY_FORM);
  const [index, setIndex] = useState(0);
  const [shown, setShown] = useState<string | null>(null); // the current slide's refusal, shown only after the seller tried to continue
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guard = useSubmitGuard();

  // Pre-fill the name from the workspace name the seller gave at sign-up (they can change it).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await apiFetch<BusinessProfileResponse>("/api/v1/business-profile", await getToken());
        if (alive && r.suggestedName) setForm((f) => (f.business_name ? f : { ...f, business_name: r.suggestedName ?? "" }));
      } catch {
        // only a convenience; the seller can type the name
      }
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const step = STEPS[index];
  const last = index === STEPS.length - 1;

  const next = () => {
    const problem = fieldError(step.key, form);
    if (problem) {
      setShown(problem);
      return;
    }
    setShown(null);
    if (!last) {
      setIndex(index + 1);
      return;
    }
    const all = formErrors(form);
    const firstBad = STEPS.findIndex((s) => all[s.key]);
    if (firstBad >= 0) {
      setIndex(firstBad);
      setShown(all[STEPS[firstBad].key] ?? null);
      return;
    }
    void guard(async () => {
      setSaving(true);
      setError(null);
      try {
        await apiFetch("/api/v1/business-profile", await getToken(), { method: "PUT", body: JSON.stringify(toBody(form)) });
        onSaved();
      } catch (e) {
        setError(friendlyApiError(e, "Could not save your business details"));
      } finally {
        setSaving(false);
      }
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        next();
      }}
      className="flex flex-col gap-4"
      aria-label="Business details"
    >
      <div className="flex items-center justify-between text-xs" style={{ color: "var(--text-6)" }}>
        <span>
          Question {index + 1} of {STEPS.length}
        </span>
        <span
          role="progressbar"
          aria-label="Progress"
          aria-valuemin={1}
          aria-valuemax={STEPS.length}
          aria-valuenow={index + 1}
          className="h-1.5 w-28 overflow-hidden rounded-full"
          style={{ background: "var(--bg-input)" }}
        >
          <span className="block h-full rounded-full" style={{ width: `${((index + 1) / STEPS.length) * 100}%`, background: "var(--accent)" }} />
        </span>
      </div>
      <div>
        <h2 className="text-lg font-bold" style={{ color: "var(--text-1)" }}>
          {step.title}
        </h2>
        <p className="mt-1 text-sm" style={{ color: "var(--text-6)" }}>
          {step.help}
        </p>
      </div>
      <ProfileField
        key={step.key}
        field={step.key}
        label={step.title}
        form={form}
        autoFocus
        error={shown}
        onChange={(f) => {
          setForm(f);
          setShown(null);
        }}
      />
      {error && <ErrorNotice message={error} />}
      <div className="flex gap-3">
        {index > 0 && (
          <Button type="button" variant="secondary" onClick={() => { setShown(null); setIndex(index - 1); }} disabled={saving}>
            Back
          </Button>
        )}
        <Button type="submit" loading={saving} loadingText="Saving…">
          {last ? "Finish" : "Next"}
        </Button>
      </div>
    </form>
  );
}
