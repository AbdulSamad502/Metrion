"use client";

import { useId, useState } from "react";
import type { InputHTMLAttributes } from "react";

export function FormField({
  label,
  error,
  ...inputProps
}: {
  label: string;
  error?: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const [reveal, setReveal] = useState(false);
  const isPassword = inputProps.type === "password";

  return (
    <div className="flex flex-col gap-1.5 text-left">
      <label htmlFor={id} className="text-xs font-semibold" style={{ color: "var(--text-5)" }}>
        {label}
      </label>
      <div className="relative">
        <input
          {...inputProps}
          type={isPassword && reveal ? "text" : inputProps.type}
          id={id}
          // Password managers need this to recognize the field; autoComplete is set per-field by callers.
          className="mt-focus w-full rounded-xl px-4 py-3 text-sm outline-none transition-colors"
          style={{
            background: "var(--bg-input)",
            border: `1px solid ${error ? "var(--negative)" : "var(--field-edge, var(--border-hover))"}`,
            color: "var(--text-2)",
            paddingRight: isPassword ? "3.25rem" : undefined,
          }}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setReveal((r) => !r)}
            aria-label={reveal ? "Hide password" : "Show password"}
            aria-pressed={reveal}
            className="mt-focus absolute right-2 top-1/2 inline-flex min-h-9 min-w-9 -translate-y-1/2 sm:min-h-6 sm:min-w-6 items-center justify-center rounded px-1.5 text-xs font-semibold"
            style={{ color: "var(--text-6)" }}
          >
            {reveal ? "Hide" : "Show"}
          </button>
        )}
      </div>
      {error && (
        <span className="text-xs" style={{ color: "var(--negative)" }}>
          {error}
        </span>
      )}
    </div>
  );
}
