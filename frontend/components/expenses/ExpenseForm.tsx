"use client";

import { useState } from "react";
import { friendlyApiError } from "@/lib/apiErrors";
import { buildContentBody, buildRefundBody, post, type ExpenseRecord, type FormValues, type Getter, type LedgerMeta } from "@/lib/expenseLedger";
import { paiseToInputText } from "@/lib/pnlText";
import { ErrorText, Field, SelectInput, SubmitButton, TextInput } from "@/components/cfo/primitives";

const EMPTY: FormValues = { effectiveDate: "", category: "", amount: "", vendor: "", description: "", costClass: "", channelScope: "", state: "confirmed" };

export function valuesFromRecord(r: ExpenseRecord): FormValues {
  return {
    effectiveDate: r.effectiveDate,
    category: r.category,
    amount: paiseToInputText(String(r.amountPaise)),
    vendor: r.vendor ?? "",
    description: r.description ?? "",
    costClass: "",
    channelScope: r.channelScope ?? "",
    state: "confirmed",
  };
}

/** Manual entry, and the correction of an existing record. An edit never overwrites: it is sent to the backend as a linked correction (a new record; the original is
 * voided). The amount is parsed to integer paise by `rupeesToPaise` and sent as a string; a server refusal (permission, a vendor that looks like an amount, a limit)
 * is shown in place and nothing the seller typed is lost. */
export function ExpenseForm({
  getToken, meta, correcting, onSaved, onCancel,
}: {
  getToken: Getter;
  meta: LedgerMeta;
  correcting: ExpenseRecord | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [v, setV] = useState<FormValues>(correcting ? valuesFromRecord(correcting) : EMPTY);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<FormValues>) => setV((cur) => ({ ...cur, ...patch }));
  const category = meta.categories.find((c) => c.id === v.category);

  const submit = async () => {
    const built = buildContentBody(v, correcting ? (reason.trim() ? { reason: reason.trim() } : {}) : { state: v.state });
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post(getToken, correcting ? `/${correcting.id}/correct` : "", built.body);
      if (!correcting) setV(EMPTY);
      onSaved();
    } catch (e) {
      setError(friendlyApiError(e, "Could not save the expense"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {correcting && (
        <p className="t-body-sm" style={{ color: "var(--text-5)" }}>
          Correcting {correcting.vendor ?? correcting.categoryLabel} ({correcting.effectiveDate}). The original stays on record and is marked voided; this saves a new linked entry.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Date"><TextInput type="date" value={v.effectiveDate} onChange={(x) => set({ effectiveDate: x })} /></Field>
        <Field label="Category">
          <SelectInput
            value={v.category}
            onChange={(x) => set({ category: x })}
            options={[{ value: "", label: "Choose a category" }, ...meta.categories.map((c) => ({ value: c.id, label: c.label }))]}
          />
        </Field>
        <Field label="Amount (₹)"><TextInput value={v.amount} onChange={(x) => set({ amount: x })} placeholder="e.g. 1,250.50" /></Field>
        <Field label="Vendor"><TextInput value={v.vendor} onChange={(x) => set({ vendor: x })} placeholder="Who was paid" /></Field>
        <Field label="Description"><TextInput value={v.description} onChange={(x) => set({ description: x })} placeholder="What it was for" /></Field>
        <Field label="Channel">
          <SelectInput
            value={v.channelScope}
            onChange={(x) => set({ channelScope: x })}
            options={[{ value: "", label: "Whole business" }, ...meta.channelTags.map((t) => ({ value: t, label: t }))]}
          />
        </Field>
        <Field label="Cost class">
          <SelectInput
            value={v.costClass}
            onChange={(x) => set({ costClass: x })}
            options={[{ value: "", label: category ? `Default for ${category.label}` : "Default for the category" }, ...meta.costClasses.map((c) => ({ value: c, label: c.charAt(0) + c.slice(1).toLowerCase() }))]}
          />
        </Field>
        {!correcting && (
          <Field label="Status">
            <SelectInput
              value={v.state}
              onChange={(x) => set({ state: x as FormValues["state"] })}
              options={[{ value: "confirmed", label: "Confirmed" }, { value: "pending_review", label: "Pending review" }, { value: "draft", label: "Draft" }]}
            />
          </Field>
        )}
        {correcting && <Field label="Reason for the correction"><TextInput value={reason} onChange={setReason} /></Field>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <SubmitButton primary onClick={submit} busy={busy} label={correcting ? "Save correction" : "Save expense"} busyLabel="Saving…" />
        {correcting && <SubmitButton onClick={onCancel} busy={false} label="Cancel" busyLabel="Cancel" />}
      </div>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

/** Void: a record is never deleted. A reason is required, and the record stays on file, voided. */
export function VoidPanel({ getToken, record, onDone, onCancel }: { getToken: Getter; record: ExpenseRecord; onDone: () => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!reason.trim()) {
      setError("Enter a reason. A voided expense stays on record with its reason.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post(getToken, `/${record.id}/void`, { reason: reason.trim() });
      onDone();
    } catch (e) {
      setError(friendlyApiError(e, "Could not void the expense"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3 py-3">
      <Field label="Reason"><TextInput value={reason} onChange={setReason} placeholder="Why this expense is being voided" /></Field>
      <div className="flex items-center gap-3">
        <SubmitButton primary onClick={submit} busy={busy} label="Void expense" busyLabel="Voiding…" />
        <SubmitButton onClick={onCancel} busy={false} label="Keep it" busyLabel="Keep it" />
      </div>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}

/** Refund or credit note: entered as a positive amount, saved as a negative record linked to the original and dated in its own period. */
export function RefundPanel({ getToken, record, onDone, onCancel }: { getToken: Getter; record: ExpenseRecord; onDone: () => void; onCancel: () => void }) {
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    const built = buildRefundBody(date, amount, description);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await post(getToken, `/${record.id}/refund`, built.body);
      onDone();
    } catch (e) {
      setError(friendlyApiError(e, "Could not record the refund"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3 py-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field label="Refund date"><TextInput type="date" value={date} onChange={setDate} /></Field>
        <Field label="Refund amount (₹)"><TextInput value={amount} onChange={setAmount} /></Field>
        <Field label="Note"><TextInput value={description} onChange={setDescription} /></Field>
      </div>
      <div className="flex items-center gap-3">
        <SubmitButton primary onClick={submit} busy={busy} label="Record refund" busyLabel="Saving…" />
        <SubmitButton onClick={onCancel} busy={false} label="Cancel" busyLabel="Cancel" />
      </div>
      <ErrorText>{error}</ErrorText>
    </div>
  );
}
