"use client";

import { useClerk } from "@clerk/nextjs";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
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
    const top = active.getBoundingClientRect().top - nav.getBoundingClientRect().top + nav.scrollTop;
    ind.style.opacity = "1";
    ind.style.height = `${active.getBoundingClientRect().height}px`;
    ind.style.transform = `translateY(${top}px)`;
  };

  useLayoutEffect(placeIndicator, [pathname, collapsed, mobileOpen]);
  // Re-place whenever anything that moves rows changes after first paint: web fonts loading, the
  // viewport or text size changing, a row resizing (badges, the attention dot), the nav resizing.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const ro = new ResizeObserver(placeIndicator);
    ro.observe(nav);
    nav.querySelectorAll<HTMLElement>(".mt-nav-item").forEach((el) => ro.observe(el));
    void document.fonts?.ready.then(placeIndicator);
    window.addEventListener("resize", placeIndicator);
    return () => {
      ro.disconnect();
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
        className={`mt-sidebar fixed inset-y-0 left-0 z-[70] flex h-screen w-[264px] flex-shrink-0 flex-col transition-[transform,width] duration-200 ${overlay ? "" : "lg:static lg:z-auto lg:translate-x-0"} ${
          mobileOpen ? "translate-x-0" : `invisible -translate-x-full ${overlay ? "" : "lg:visible"}` // off-screen and out of the tab order until opened
        } ${collapsed ? "lg:w-[76px]" : "lg:w-60"}`}
      >
        <div className={`flex items-center gap-2.5 px-5 pb-4 pt-5 ${collapsed ? "lg:justify-center lg:px-0" : ""}`}>
          <Image src="/metrion-mark.png" alt="Metrion" width={44} height={28} className="flex-shrink-0" priority />
          <div className={`min-w-0 ${collapsed ? "lg:hidden" : ""}`}>
            <div className="t-section font-bold leading-none" style={{ color: "var(--text-1)" }}>
              Metrion
            </div>
            <div className="mt-1 whitespace-nowrap t-nano font-semibold tracking-[0.11em]" style={{ color: "var(--text-tagline)" }}>
              ENGINE OF GROWTH
            </div>
          </div>
        </div>

        <nav ref={navRef} className="relative flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 pb-3" aria-label="Sections">
          <div
            ref={indicatorRef}
            aria-hidden
            className="mt-nav-indicator pointer-events-none absolute left-3 right-3 top-0 rounded-xl opacity-0"
            style={{ transition: "transform 0.28s cubic-bezier(.16,1,.3,1), height 0.2s ease, opacity 0.2s ease" }}
          />
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="mb-0.5">
              <div
                className={`px-3 pb-1.5 pt-3 [@media(max-height:800px)]:pt-1.5 t-nano font-bold uppercase tracking-wider ${collapsed ? "lg:invisible lg:h-3 lg:p-0" : ""}`}
                style={{ color: "var(--text-6)" }}
              >
                {group.label}
              </div>
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

          <div className="flex-1" />
          <div className="my-2 h-px [@media(max-height:800px)]:my-1" style={{ background: "var(--border-subtle)" }} />
          <div
            className={`px-3 pb-1.5 pt-1 t-nano font-bold uppercase tracking-wider ${collapsed ? "lg:invisible lg:h-0 lg:p-0" : ""}`}
            style={{ color: "var(--text-6)" }}
          >
            {SYSTEM_GROUP_LABEL}
          </div>
          {FOOTER_NAV.map((item) => (
            <NavRow
              key={item.id}
              item={item}
              active={isActive(item, pathname)}
              collapsed={collapsed}
              attention={item.id === "notifications" ? attentionCount : 0}
            />
          ))}
        </nav>

        <div className="hidden px-3 pb-2 lg:block">
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-pressed={collapsed}
            className="mt-btn mt-focus flex w-full items-center justify-center gap-2 rounded-xl py-2 t-meta-sm font-semibold"
            style={{ color: "var(--text-6)", border: "1px solid var(--border-subtle)" }}
          >
            <span style={{ display: "inline-flex", transform: collapsed ? "rotate(180deg)" : "none", transition: "transform 0.2s ease" }}>
              <Icon name="collapse" size={14} />
            </span>
            {!collapsed && "Collapse"}
          </button>
        </div>

        <div className={`flex items-center gap-2.5 p-3.5 ${collapsed ? "lg:justify-center lg:px-0" : ""}`} style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <div
            className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-[14px] text-xs font-bold"
            style={{ background: "var(--fill-hover)", color: "var(--text-3)" }}
            title={collapsed ? `${userName} · ${roleLabel}` : undefined}
          >
            {initials || "?"}
          </div>
          <div className={`min-w-0 ${collapsed ? "lg:hidden" : ""}`}>
            <div className="truncate t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>
              {userName}
            </div>
            <div className="truncate t-micro" style={{ color: "var(--text-5)" }}>
              {roleLabel}
            </div>
          </div>
          <button
            type="button"
            onClick={() => signOut({ redirectUrl: "/" })}
            aria-label="Sign out"
            title="Sign out"
            className={`mt-btn mt-focus ml-auto flex-shrink-0 rounded-lg p-1.5 ${collapsed ? "lg:hidden" : ""}`}
            style={{ color: "var(--text-6)" }}
          >
            <Icon name="logout" size={15} />
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
        <Icon name={item.icon} size={18} />
      </span>
      {label}
      {item.soon && (
        <span
          className={`rounded px-1.5 py-0.5 t-nano font-semibold ${collapsed ? "lg:hidden" : ""}`}
          style={{ background: "var(--border-subtle)", color: "var(--text-7)" }}
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
  const className = `mt-nav-item mt-focus flex min-h-[44px] items-center gap-3 rounded-xl px-3 py-2 lg:min-h-0 t-body ${collapsed ? "lg:justify-center lg:px-0" : ""}`;
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
