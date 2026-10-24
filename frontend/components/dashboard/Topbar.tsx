"use client";

import { ThemeToggle } from "./ThemeToggle";
import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";

/** The page header, laid out as a control surface:
 *   LEFT    identity — where you are (section eyebrow) and what this page is for
 *   CENTER  context — only when the page supplies something genuinely useful (never decoration)
 *   RIGHT   actions — page actions, notifications, and the CEO shortcut (hidden on the CEO Hub itself)
 * There is deliberately no date-range picker: no dashboard query takes a global range. */
export function Topbar({
  title,
  subtitle,
  eyebrow,
  attentionCount,
  onOpenMenu,
  context,
  actions,
  showCeoShortcut,
}: {
  title: string;
  subtitle: string;
  eyebrow?: string;
  attentionCount: number;
  onOpenMenu: () => void;
  context?: ReactNode;
  actions?: ReactNode;
  showCeoShortcut: boolean;
}) {
  return (
    <header
      className="mt-topbar sticky top-0 z-10 flex flex-shrink-0 items-center gap-4 px-4 py-4 sm:px-8"
    >
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Open navigation"
        className="mt-btn mt-focus flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl lg:hidden"
        style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}
      >
        <Icon name="menu" size={18} />
      </button>

      <div className="min-w-0 flex-shrink">
        {eyebrow && (
          <div className="mt-eyebrow hidden truncate sm:block" style={{ color: "var(--text-6)" }}>
            {eyebrow}
          </div>
        )}
        <h1 className="t-page-title truncate" style={{ color: "var(--text-1)" }}>
          {title}
        </h1>
        <p className="t-meta mt-1 hidden truncate md:block" style={{ color: "var(--text-5)" }}>
          {subtitle}
        </p>
      </div>

      <div className="hidden min-w-0 flex-1 items-center justify-center lg:flex">{context}</div>
      <div className="flex-1 lg:hidden" />

      <div className="flex flex-shrink-0 items-center gap-2">
        {actions}
        <span className="hidden sm:inline-flex">
          <ThemeToggle />
        </span>
        <Link
          href="/dashboard/notifications"
          aria-label={attentionCount > 0 ? `Action Center — ${attentionCount} need attention` : "Action Center"}
          title="Action Center"
          className="mt-btn mt-focus relative flex h-10 w-10 items-center justify-center rounded-xl"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}
        >
          <Icon name="notifications" size={17} />
          {attentionCount > 0 && (
            <span
              className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full"
              style={{ background: "var(--accent)", boxShadow: "0 0 0 1.5px var(--bg-base)" }}
              aria-hidden
            />
          )}
        </Link>
        {showCeoShortcut && (
          <Link
            href="/dashboard/ceo-hub"
            className="mt-btn mt-btn-secondary mt-focus flex min-h-10 items-center gap-2 whitespace-nowrap rounded-xl px-4 py-2 t-body font-semibold"
          >
            <span className="hidden sm:inline">CEO Hub</span>
            <span className="sm:hidden">CEO</span>
            <Icon name="arrow" size={13} strokeWidth={1.9} />
          </Link>
        )}
      </div>
    </header>
  );
}
