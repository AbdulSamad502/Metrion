"use client";

import { useId, useState } from "react";
import type { InputHTMLAttributes } from "react";

export function FormField({
  label,
  error,
  soft = false,
  ...inputProps
}: {
  label: string;
  error?: string;
  /** The softer, rounder look the redesigned screens use. The default is unchanged. */
  soft?: boolean;
} & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const [reveal, setReveal] = useState(false);
  const isPassword = inputProps.type === "password";

  if (soft) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, textAlign: "left" }}>
        <label htmlFor={id} className="ov-meta" style={{ fontWeight: 700 }}>
          {label}
        </label>
        <div style={{ position: "relative" }}>
          <input
            {...inputProps}
            type={isPassword && reveal ? "text" : inputProps.type}
            id={id}
            aria-invalid={error ? true : undefined}
            className="ov-input"
            style={isPassword ? { paddingRight: 72 } : undefined}
          />
          {isPassword && (
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              aria-label={reveal ? "Hide password" : "Show password"}
              aria-pressed={reveal}
              className="ov-btn ov-btn--ghost min-h-10 min-w-10"
              style={{ position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)", minHeight: 40, minWidth: 40 }}
            >
              {reveal ? "Hide" : "Show"}
            </button>
          )}
        </div>
        {error && <span className="ov-meta" style={{ color: "var(--ov-bad)" }}>{error}</span>}
      </div>
    );
  }

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
            className="mt-focus absolute right-2 top-1/2 inline-flex min-h-10 min-w-10 -translate-y-1/2 items-center justify-center rounded px-1.5 text-xs font-semibold"
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
