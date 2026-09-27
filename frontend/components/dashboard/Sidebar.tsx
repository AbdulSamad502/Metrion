"use client";

import { useClerk } from "@clerk/nextjs";
import Link from "next/link";

type NavItem = { label: string; href?: string; soon?: boolean };
type NavGroup = { label: string; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  { label: "Profit Intelligence", items: [{ label: "Overview", href: "/dashboard" }, { label: "CEO Hub", href: "/dashboard/ceo-hub" }] },
  { label: "Analysis", items: [{ label: "Products" }, { label: "Competitors", href: "/dashboard/ceo-hub" }] },
  {
    label: "Operations",
    items: [
      { label: "Orders", soon: true },
      { label: "Customers", soon: true },
      { label: "CFO", href: "/dashboard/cfo" },
      { label: "Marketing" },
      { label: "Reports", soon: true },
    ],
  },
];

const FOOTER_NAV: NavItem[] = [
  { label: "Agents" },
  { label: "Agent Cart" },
  { label: "Settings", href: "/settings" },
  { label: "Notifications" },
];

/** Static app-shell sidebar — auth.md scope note: only the entry screen (+ account
 * security, per the later auth-completeness pass) ships now, so every item besides
 * "Overview" and "Settings" is inert chrome (matches docs/design/frontend-design), not a
 * real route yet. */
export function Sidebar({
  userName,
  roleLabel,
  active,
}: {
  userName: string;
  roleLabel: string;
  active: "Overview" | "Settings" | "CEO Hub" | "CFO";
}) {
  const { signOut } = useClerk();
  const initials = userName
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div
      className="flex h-screen w-60 flex-shrink-0 flex-col"
      style={{ background: "var(--bg-sidebar)", borderRight: "1px solid var(--border-subtle)" }}
    >
      <div className="flex items-center gap-2 px-5 pb-4 pt-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md" style={{ background: "var(--accent)" }}>
          <span className="text-xs font-black" style={{ color: "var(--accent-on-fill)" }}>
            M
          </span>
        </div>
        <div>
          <div className="text-sm font-bold leading-none" style={{ color: "var(--text-1)" }}>
            Metrion
          </div>
          <div className="mt-1 text-[8.5px] font-semibold tracking-widest" style={{ color: "var(--text-tagline)" }}>
            ENGINE OF GROWTH
          </div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 pb-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-1">
            <div
              className="px-3 pb-1.5 pt-3 text-[10px] font-bold uppercase tracking-wider"
              style={{ color: "var(--text-group-label)" }}
            >
              {group.label}
            </div>
            {group.items.map((item) => (
              <NavRow key={item.label} item={item} active={item.label === active} />
            ))}
          </div>
        ))}

        <div className="flex-1" />
        <div className="my-2 h-px" style={{ background: "var(--border-subtle)" }} />
        {FOOTER_NAV.map((item) => (
          <NavRow key={item.label} item={item} active={item.label === active} />
        ))}
      </nav>

      <div className="flex items-center gap-2.5 p-3.5" style={{ borderTop: "1px solid var(--border-subtle)" }}>
        <div
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl text-xs font-bold"
          style={{ background: "var(--accent-border-subtle)", color: "var(--accent)" }}
        >
          {initials || "?"}
        </div>
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold" style={{ color: "var(--text-2)" }}>
            {userName}
          </div>
          <div className="truncate text-[11px]" style={{ color: "var(--text-7)" }}>
            {roleLabel}
          </div>
        </div>
        <button
          type="button"
          onClick={() => signOut({ redirectUrl: "/" })}
          aria-label="Sign out"
          className="ml-auto flex-shrink-0 rounded-lg p-1.5"
          style={{ color: "var(--text-6)" }}
        >
          <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 3H5a1.5 1.5 0 0 0-1.5 1.5v11A1.5 1.5 0 0 0 5 17h3" />
            <path d="M13 14l4-4-4-4" />
            <path d="M17 10H7.5" />
          </svg>
        </button>
      </div>
    </div>
  );
}

function NavRow({ item, active }: { item: NavItem; active: boolean }) {
  const content = (
    <>
      <span className="flex-1 truncate">{item.label}</span>
      {item.soon && (
        <span
          className="rounded px-1.5 py-0.5 text-[9.5px] font-semibold"
          style={{ background: "var(--border-subtle)", color: "var(--text-7)" }}
        >
          Soon
        </span>
      )}
    </>
  );
  const className = "flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13px]";
  const style: React.CSSProperties = {
    background: active ? "var(--accent-fill-default)" : "transparent",
    color: active ? "var(--text-1)" : "var(--text-4)",
    fontWeight: active ? 600 : 500,
  };

  if (item.href) {
    return (
      <Link href={item.href} className={className} style={style}>
        {content}
      </Link>
    );
  }
  return (
    <div className={`${className} cursor-default`} style={style}>
      {content}
    </div>
  );
}
