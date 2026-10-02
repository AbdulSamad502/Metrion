import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary";

export function Button({
  variant = "primary",
  loading,
  loadingText = "Please wait…",
  children,
  className = "",
  ...props
}: {
  variant?: Variant;
  loading?: boolean;
  loadingText?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "flex w-full cursor-pointer items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold transition duration-150 " +
    "hover:brightness-110 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 " +
    "focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:brightness-100 disabled:active:scale-100";
  const style =
    variant === "primary"
      ? { background: "var(--accent)", color: "var(--accent-on-fill)" }
      : { background: "transparent", color: "var(--text-2)", border: "1px solid var(--border-hover)" };

  return (
    <button {...props} disabled={props.disabled || loading} className={`${base} ${className}`} style={style}>
      {loading ? loadingText : children}
    </button>
  );
}

export function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.9c1.7-1.57 2.68-3.88 2.68-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.9-2.26c-.8.54-1.83.86-3.06.86-2.35 0-4.34-1.59-5.05-3.72H.9v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.95 10.7A5.4 5.4 0 0 1 3.67 9c0-.59.1-1.17.28-1.7V4.97H.9A9 9 0 0 0 0 9c0 1.45.35 2.83.9 4.03l3.05-2.33Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.51.46 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .9 4.97L3.95 7.3C4.66 5.17 6.65 3.58 9 3.58Z"
      />
    </svg>
  );
}
