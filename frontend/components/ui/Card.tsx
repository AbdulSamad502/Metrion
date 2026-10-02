"use client";

import Link from "next/link";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { Icon } from "./Icon";

type Variant = "default" | "elevated" | "accent" | "locked";

/** The dashboard's glass card (Level 2 surface; `elevated`/`accent` are Level 3).
 *
 * A card is only interactive when something real is behind it:
 *   - `href`    → renders a real `<a>` (client-side navigation) — use for "this goes somewhere".
 *   - `onClick` → renders `role="button"` with Enter/Space — use for "this opens a drawer/detail".
 *   - neither   → a plain, non-interactive surface with no hover or pointer styling.
 * `selected` marks the current item (accent edge + elevated glass); `disabled` keeps it visible but
 * inert and announces it as such. Interactive cards get a visible keyboard focus ring.
 *
 * Put an affordance inside the card with `<CardCta>` so "this is clickable" is never hover-only. */
export function Card({
  children,
  variant = "default",
  onClick,
  href,
  selected = false,
  disabled = false,
  className = "",
  style,
  ariaLabel,
}: {
  children: ReactNode;
  variant?: Variant;
  onClick?: () => void;
  href?: string;
  selected?: boolean;
  disabled?: boolean;
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
}) {
  const interactive = !disabled && Boolean(onClick || href);
  const classes = [
    "mt-dash-card",
    variant === "elevated" && "mt-dash-card--elevated",
    variant === "accent" && "mt-dash-card--accent",
    variant === "locked" && "mt-dash-card--locked",
    interactive && "mt-dash-card--interactive mt-focus",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (href && !disabled) {
    return (
      <Link href={href} className={`${classes} block`} style={style} aria-label={ariaLabel} aria-current={selected ? "true" : undefined}>
        {children}
      </Link>
    );
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!onClick) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <div
      className={classes}
      style={style}
      onClick={interactive ? onClick : undefined}
      onKeyDown={interactive ? onKeyDown : undefined}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={ariaLabel}
      aria-disabled={disabled ? "true" : undefined}
      aria-current={selected ? "true" : undefined}
      data-selected={selected ? "true" : undefined}
    >
      {children}
    </div>
  );
}

/** The always-visible affordance of an interactive card: a label and arrow that firm up on hover or
 * focus. Presentational only (the card itself is the control), so it is not a link or button. */
export function CardCta({ children }: { children: ReactNode }) {
  return (
    <span className="mt-card-cta t-meta inline-flex items-center gap-1 font-semibold">
      {children}
      <Icon name="arrow" size={12} strokeWidth={1.9} />
    </span>
  );
}
