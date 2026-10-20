"use client";

import { useId } from "react";
import {
  MARKETPLACE_OPTIONS,
  MAX_LENGTH,
  PRICE_OPTIONS,
  STAGE_OPTIONS,
  STATES,
  type BusinessProfileForm,
  type FieldKey,
  type Marketplace,
} from "@/lib/businessProfile";

const INPUT_STYLE = { background: "var(--bg-input)", color: "var(--text-2)" } as const;
const edge = (error?: string | null) => `1px solid ${error ? "var(--negative)" : "var(--field-edge, var(--border-hover))"}`;

/** One business-profile input, chosen by field key. Shared by the first-run slides and the Settings form so both ask exactly the same way. `label` names the control for
 * assistive tech; an error is announced next to it. */
export function ProfileField({
  field,
  label,
  form,
  onChange,
  error,
  autoFocus,
}: {
  field: FieldKey;
  label: string;
  form: BusinessProfileForm;
  onChange: (next: BusinessProfileForm) => void;
  error?: string | null;
  autoFocus?: boolean;
}) {
  const id = useId();
  const set = <K extends FieldKey>(k: K, v: BusinessProfileForm[K]) => onChange({ ...form, [k]: v });
  const errorId = `${id}-err`;
  const common = { id, "aria-invalid": error ? true : undefined, "aria-describedby": error ? errorId : undefined } as const;

  let control: React.ReactNode;
  if (field === "description") {
    control = (
      <textarea
        {...common}
        rows={3}
        maxLength={MAX_LENGTH.description}
        autoFocus={autoFocus}
        value={form.description}
        onChange={(e) => set("description", e.target.value)}
        className="mt-focus w-full resize-none rounded-xl px-4 py-3 text-sm outline-none"
        style={{ ...INPUT_STYLE, border: edge(error) }}
      />
    );
  } else if (field === "business_name" || field === "categories" || field === "target_customer") {
    control = (
      <input
        {...common}
        type="text"
        maxLength={MAX_LENGTH[field]}
        autoFocus={autoFocus}
        value={form[field]}
        onChange={(e) => set(field, e.target.value)}
        className="mt-focus w-full rounded-xl px-4 py-3 text-sm outline-none"
        style={{ ...INPUT_STYLE, border: edge(error) }}
      />
    );
  } else if (field === "state") {
    control = (
      <select
        {...common}
        autoFocus={autoFocus}
        value={form.state}
        onChange={(e) => set("state", e.target.value)}
        className="mt-focus w-full rounded-xl px-4 py-3 text-sm outline-none"
        style={{ ...INPUT_STYLE, border: edge(error) }}
      >
        <option value="">Choose a state…</option>
        {STATES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    );
  } else if (field === "marketplaces") {
    control = (
      <div role="group" aria-label={label} className="flex flex-wrap gap-2">
        {MARKETPLACE_OPTIONS.map((o) => {
          const on = form.marketplaces.includes(o.value);
          return (
            <Choice
              key={o.value}
              role="checkbox"
              checked={on}
              label={o.label}
              onClick={() =>
                set("marketplaces", on ? form.marketplaces.filter((m) => m !== o.value) : ([...form.marketplaces, o.value] as Marketplace[]))
              }
            />
          );
        })}
      </div>
    );
  } else {
    const options = field === "price_segment" ? PRICE_OPTIONS : STAGE_OPTIONS;
    control = (
      <div role="radiogroup" aria-label={label} className="flex flex-col gap-2">
        {options.map((o) => (
          <Choice key={o.value} role="radio" checked={form[field] === o.value} label={o.label} hint={o.hint} onClick={() => set(field, o.value as never)} />
        ))}
      </div>
    );
  }

  const isGroup = field === "marketplaces" || field === "price_segment" || field === "business_stage";
  return (
    <div className="flex flex-col gap-1.5 text-left">
      {isGroup ? (
        <span className="text-xs font-semibold" style={{ color: "var(--text-5)" }}>
          {label}
        </span>
      ) : (
        <label htmlFor={id} className="text-xs font-semibold" style={{ color: "var(--text-5)" }}>
          {label}
        </label>
      )}
      {control}
      {error && (
        <p id={errorId} role="alert" className="text-xs" style={{ color: "var(--negative)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

function Choice({ role, checked, label, hint, onClick }: { role: "radio" | "checkbox"; checked: boolean; label: string; hint?: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role={role}
      aria-checked={checked}
      onClick={onClick}
      className="mt-focus flex min-h-[44px] cursor-pointer flex-col items-start rounded-xl px-4 py-2.5 text-left text-sm transition-colors"
      style={{
        background: checked ? "var(--accent-fill-subtle)" : "var(--bg-input)",
        border: `1px solid ${checked ? "var(--accent)" : "var(--field-edge, var(--border-hover))"}`,
        color: "var(--text-2)",
      }}
    >
      <span className="font-semibold">{label}</span>
      {hint && (
        <span className="text-xs" style={{ color: "var(--text-6)" }}>
          {hint}
        </span>
      )}
    </button>
  );
}
