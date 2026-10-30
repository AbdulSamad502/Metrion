"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { ModalPortal } from "@/components/ui/ModalPortal";
import { ProfileField } from "@/components/profile/ProfileField";
import { ApiError, apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import {
  EMPTY_FORM,
  STEPS,
  formErrors,
  fromRead,
  toBody,
  type BusinessProfileForm,
  type BusinessProfileResponse,
  type FieldKey,
} from "@/lib/businessProfile";
import { useModalFocus } from "@/lib/useModalFocus";
import { useSubmitGuard } from "@/lib/useSubmitGuard";

/** Settings → "Business details": a dialog with all eight fields, pre-filled from what is saved. Every field is mandatory: a save with anything blank is refused here
 * (the first problem is announced and nothing is sent) and again by the server. */
export function BusinessDetailsDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { getToken } = useAuth();
  const ref = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState<BusinessProfileForm | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [canEdit, setCanEdit] = useState(true);
  const [errors, setErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const guard = useSubmitGuard();
  useModalFocus(true, ref, onClose);

  const load = async () => {
    setLoadError(null);
    try {
      const r = await apiFetch<BusinessProfileResponse>("/api/v1/business-profile", await getToken());
      setForm(r.profile ? fromRead(r.profile) : { ...EMPTY_FORM, business_name: r.suggestedName ?? "" });
    } catch (e) {
      setLoadError(friendlyApiError(e, "Could not load your business details"));
    }
  };

  useEffect(() => {
    (async () => {
      await load();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const found = formErrors(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return; // every field is mandatory: nothing is sent while any is blank or invalid
    void guard(async () => {
      setSaving(true);
      setSaveError(null);
      try {
        await apiFetch("/api/v1/business-profile", await getToken(), { method: "PUT", body: JSON.stringify(toBody(form)) });
        onSaved();
        onClose();
      } catch (err) {
        if (err instanceof ApiError && err.status === 403) setCanEdit(false);
        setSaveError(friendlyApiError(err, "Could not save your business details"));
      } finally {
        setSaving(false);
      }
    });
  };

  return (
    <ModalPortal>
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4 py-10" style={{ background: "var(--ov-scrim, rgba(0,0,0,0.65))" }}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="business-details-title"
        className="mt-panel w-full max-w-xl outline-none"
        style={{ padding: "22px 24px", background: "var(--bg-popover)", border: "1px solid var(--border-default)" }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="business-details-title" className="text-base font-bold" style={{ color: "var(--text-2)" }}>
              Business details
            </h2>
            <p className="mt-1 text-xs" style={{ color: "var(--text-6)" }}>
              Every answer is required. Metrion’s assistants use a short summary of these to tailor their advice to your business.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="mt-focus rounded-lg px-2 py-1 text-sm" style={{ color: "var(--text-5)" }}>
            ✕
          </button>
        </div>

        {loadError && <div className="mt-4"><ErrorNotice message={loadError} onRetry={load} /></div>}
        {!form && !loadError && <div className="mt-4"><LoadingState label="Loading your business details…" /></div>}

        {form && (
          <form onSubmit={save} noValidate className="mt-5 flex flex-col gap-4">
            {STEPS.map((s) => (
              <ProfileField
                key={s.key}
                field={s.key}
                label={s.title}
                form={form}
                error={errors[s.key]}
                onChange={(f) => {
                  setForm(f);
                  setErrors((prev) => ({ ...prev, [s.key]: undefined }));
                }}
              />
            ))}
            {Object.keys(errors).some((k) => errors[k as FieldKey]) && (
              <p role="alert" className="text-sm" style={{ color: "var(--negative)" }}>
                Please fill in every field before saving.
              </p>
            )}
            {saveError && <ErrorNotice message={saveError} />}
            <div className="flex gap-3">
              <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
                Cancel
              </Button>
              <Button type="submit" loading={saving} loadingText="Saving…" disabled={!canEdit}>
                Save details
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
    </ModalPortal>
  );
}
