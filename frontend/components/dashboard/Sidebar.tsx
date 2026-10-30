"use client";

import { useClerk } from "@clerk/nextjs";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import "./sidebar.css";
import "@/components/overview/overview.css";
import { FOOTER_NAV, NAV_GROUPS, SYSTEM_GROUP_LABEL, isActive, type NavItem } from "@/lib/navigation";

/** The persistent app navigation (docs/design/frontend-design). Active state comes from the
 * URL, not a prop, so it can never disagree with the page; a single indicator slides to the
 * active row. Desktop can collapse to icons; below `lg` it becomes a drawer opened from the
 * Topbar. Items without a real page render as inert "Soon" rows. */
export function Sidebar({
  userName,
  roleLabel,
  attentionCount,
  collapsed,
  onToggleCollapsed,
  mobileOpen,
  onCloseMobile,
  overlay = false,
}: {
  userName: string;
  roleLabel: string;
  attentionCount: number;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  /** Behave as the slide-in drawer at every width (the CEO Hub keeps the navigation closed until it is asked for). */
  overlay?: boolean;
}) {
  const { signOut } = useClerk();
  const pathname = usePathname();
  const navRef = useRef<HTMLElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);
  const indicatorRef = useRef<HTMLDivElement | null>(null);

  const initials = userName
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  // The mobile drawer is a modal-style overlay below the desktop breakpoint. Escape closes it (kept current through a ref so the effect below does not re-run).
  const closeRef = useRef(onCloseMobile);
  useEffect(() => { closeRef.current = onCloseMobile; });

  // Focus moves into the drawer when it opens, Tab stays inside while it is open, and focus returns to whatever opened it when it closes.
  useEffect(() => {
    if (!mobileOpen) return;
    const aside = asideRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusables = () => Array.from(aside?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? []).filter((el) => { const cs = getComputedStyle(el); return cs.display !== "none" && cs.visibility !== "hidden"; });
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { closeRef.current(); return; }
      if (e.key !== "Tab") return;
      const list = focusables();
      if (list.length === 0) return;
      const first = list[0], last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (aside && !aside.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [mobileOpen]);

  // Slide the indicator to the active row. Imperative on purpose: it is pure presentation, so no
  // state/re-render is needed, and it runs before paint so it never flashes in the wrong place.
  const placeIndicator = () => {
    const nav = navRef.current;
    const ind = indicatorRef.current;
    if (!nav || !ind) return;
    const active = nav.querySelector<HTMLElement>('[aria-current="page"]');
    if (!active) {
      ind.style.opacity = "0";
      return;
    }
    // Measured from bounding boxes (not offsetTop) so it stays correct inside the scrolling nav,
    // whatever the offsetParent chain is.
    // Under the dashboard's reduced page size (CSS zoom) rects are in screen pixels but the indicator is laid out in zoomed pixels, so divide by the scale.
    const navRect = nav.getBoundingClientRect();
    const scale = nav.offsetHeight > 0 && navRect.height > 0 ? navRect.height / nav.offsetHeight : 1;
    const rect = active.getBoundingClientRect();
    const top = (rect.top - navRect.top) / scale + nav.scrollTop;
    ind.style.opacity = "1";
    ind.style.height = `${rect.height / scale}px`;
    ind.style.transform = `translateY(${top}px)`;
  };

  useLayoutEffect(placeIndicator, [pathname, collapsed, mobileOpen]);
  // Re-place whenever anything that moves rows changes after first paint: web fonts loading, the
  // viewport or text size changing, a row resizing (badges, the attention dot), the nav resizing.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(placeIndicator) : null; // absent in very old browsers
    ro?.observe(nav);
    nav.querySelectorAll<HTMLElement>(".mt-nav-item").forEach((el) => ro?.observe(el));
    void document.fonts?.ready.then(placeIndicator);
    window.addEventListener("resize", placeIndicator);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", placeIndicator);
    };
  }, [collapsed]);

  // Navigating on mobile closes the drawer.
  useEffect(() => {
    onCloseMobile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return (
    <>
      <div
        className={`mt-scrim fixed inset-0 z-[65] ${overlay ? "" : "lg:hidden"}`}
        style={{
          opacity: mobileOpen ? 1 : 0,
          pointerEvents: mobileOpen ? "auto" : "none",
          transition: "opacity 0.2s ease",
        }}
        onClick={onCloseMobile}
        aria-hidden
      />
      <aside
        ref={asideRef}
        aria-label="Primary"
        className={`mt-sidebar ${collapsed ? "sb-collapsed" : ""} fixed inset-y-0 left-0 z-[70] flex h-screen w-[264px] flex-shrink-0 flex-col transition-[transform,width] duration-200 ${overlay ? "" : "lg:static lg:z-auto lg:translate-x-0"} ${
          mobileOpen ? "translate-x-0" : `invisible -translate-x-full ${overlay ? "" : "lg:visible"}` // off-screen and out of the tab order until opened
        } ${collapsed ? "lg:w-[76px]" : "lg:w-60"}`}
      >
        <div className={`sb-brand ${collapsed ? "lg:justify-center" : ""}`}>
          <span role="img" aria-label="Metrion" className={`sb-brand-mark ${collapsed ? "lg:hidden" : ""}`} />
          <div className={`min-w-0 ${collapsed ? "lg:hidden" : ""}`}>
            <div className="sb-brand-name">Metrion</div>
            <div className="sb-brand-tag">Engine of growth</div>
          </div>
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-pressed={collapsed}
            className="sb-toggle mt-focus hidden lg:inline-flex"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <rect x="3" y="4" width="18" height="16" rx="4" />
              <path d="M10 4v16" />
            </svg>
          </button>
        </div>

        <nav ref={navRef} className="sb-nav sb-scroll relative flex-1 overflow-y-auto" aria-label="Sections">
          <div
            ref={indicatorRef}
            aria-hidden
            className="mt-nav-indicator pointer-events-none absolute left-4 right-4 top-0 opacity-0"
            style={{ transition: "transform 0.28s cubic-bezier(.16,1,.3,1), height 0.2s ease, opacity 0.2s ease" }}
          />
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="sb-group">
              <div className={`sb-label ${collapsed ? "lg:invisible lg:h-2 lg:p-0" : ""}`}>{group.label}</div>
              {group.items.map((item) => (
                <NavRow
                  key={item.id}
                  item={item}
                  active={isActive(item, pathname)}
                  collapsed={collapsed}
                  attention={item.id === "notifications" ? attentionCount : 0}
                />
              ))}
            </div>
          ))}

          <div className="sb-system">
            <div className="sb-group">
              <div className={`sb-label ${collapsed ? "lg:invisible lg:h-0 lg:p-0" : ""}`}>{SYSTEM_GROUP_LABEL}</div>
              {FOOTER_NAV.map((item) => (
                <NavRow
                  key={item.id}
                  item={item}
                  active={isActive(item, pathname)}
                  collapsed={collapsed}
                  attention={item.id === "notifications" ? attentionCount : 0}
                />
              ))}
            </div>
          </div>
        </nav>

        <div className="sb-user">
          <div className="sb-avatar" title={collapsed ? `${userName} · ${roleLabel}` : undefined}>
            {initials || "?"}
          </div>
          <div className={`min-w-0 ${collapsed ? "lg:hidden" : ""}`}>
            <div className="sb-user-name truncate">{userName}</div>
            <div className="sb-user-role truncate">{roleLabel}</div>
          </div>
          <button
            type="button"
            onClick={() => signOut({ redirectUrl: "/" })}
            aria-label="Sign out"
            title="Sign out"
            className={`sb-signout mt-focus ${collapsed ? "lg:hidden" : ""}`}
          >
            <Icon name="logout" size={18} />
          </button>
        </div>
      </aside>
    </>
  );
}

function NavRow({
  item,
  active,
  collapsed,
  attention = 0,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  attention?: number;
}) {
  const label = (
    <span className={`flex-1 truncate ${collapsed ? "lg:hidden" : ""}`}>{item.label}</span>
  );
  const body = (
    <>
      <span className="flex-shrink-0" style={{ color: active ? "var(--accent)" : undefined }}>
        <Icon name={item.icon} size={20} />
      </span>
      {label}
      {item.soon && (
        <span
          className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ${collapsed ? "lg:hidden" : ""}`}
          style={{ background: "var(--border-subtle)", color: "var(--text-5)" }}
        >
          Soon
        </span>
      )}
      {attention > 0 && (
        <>
          <span
            className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${collapsed ? "lg:absolute lg:right-4 lg:top-2" : ""}`}
            style={{ background: "var(--accent)" }}
            aria-hidden
          />
          <span className="sr-only">{attention} items need attention</span>
        </>
      )}
    </>
  );
  const className = `mt-nav-item mt-focus flex items-center ${collapsed ? "lg:justify-center lg:px-0" : ""}`;
  const style: React.CSSProperties = {
    color: active ? "var(--text-1)" : item.soon ? "var(--text-6)" : "var(--text-4)",
    fontWeight: active ? 600 : 500,
  };

  if (item.href) {
    return (
      <Link
        href={item.href}
        className={className}
        style={style}
        aria-current={active ? "page" : undefined}
        title={collapsed ? item.label : undefined}
      >
        {body}
      </Link>
    );
  }
  return (
    <div
      className={`${className} cursor-default`}
      style={{ ...style, opacity: 0.75 }}
      aria-disabled="true"
      title={collapsed ? `${item.label} (coming soon)` : "Coming soon"}
    >
      {body}
    </div>
  );
}
