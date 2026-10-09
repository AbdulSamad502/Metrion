"use client";

import { rupeesToPaise, type CostChoice, type CostMode } from "@/lib/costInput";

const MODES: { value: CostMode; label: string }[] = [
  { value: "amount", label: "An amount" },
  { value: "none", label: "None (0), I confirm" },
  { value: "unknown", label: "Unknown" },
];

/** One cost, answered explicitly. There is no default: nothing is chosen until the seller chooses, and "unknown" means every figure that depends on it is
 * shown as unavailable rather than computed with a zero. */
export function CostInput({ label, value, onChange }: { label: string; value: CostChoice; onChange: (next: CostChoice) => void }) {
  const bad = value.mode === "amount" && value.amount.trim() !== "" && rupeesToPaise(value.amount) === null;
  return (
    <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0" data-testid={`cost-${label}`}>
      <legend className="mb-1 p-0 t-body-sm font-medium" style={{ color: "var(--text-5)" }}>{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {MODES.map((m) => (
          <label key={m.value} className="flex items-center gap-1.5 t-body-sm" style={{ color: "var(--text-3)" }}>
            <input type="radio" name={`cost-${label}`} checked={value.mode === m.value} onChange={() => onChange({ ...value, mode: m.value })} />
            {m.label}
          </label>
        ))}
      </div>
      {value.mode === "amount" && (
        <input
          aria-label={`${label} amount in rupees`}
          inputMode="decimal"
          value={value.amount}
          onChange={(e) => onChange({ ...value, amount: e.target.value })}
          placeholder="e.g. 49.50"
          className="mt-input w-full rounded-lg px-3 py-2 t-body"
          aria-invalid={bad}
        />
      )}
      {bad && <span role="alert" className="t-meta" style={{ color: "var(--negative)" }}>Enter rupees with at most two decimals, for example 49.50.</span>}
      {value.mode === "unknown" && (
        <input
          aria-label={`${label} reason`}
          value={value.reason}
          onChange={(e) => onChange({ ...value, reason: e.target.value })}
          placeholder="Why unknown? (optional)"
          className="mt-input w-full rounded-lg px-3 py-2 t-body"
        />
      )}
    </fieldset>
  );
}
