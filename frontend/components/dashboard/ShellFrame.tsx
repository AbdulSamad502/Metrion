"use client";

import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { ShellProvider } from "@/lib/ShellContext";
import { useAppSession } from "@/lib/useAppSession";
import { useNotificationsFeed } from "@/lib/useNotifications";
import { useSurfaceSheen } from "@/lib/useSurfaceSheen";
import { Sidebar } from "./Sidebar";
import { Icon } from "@/components/ui/Icon";

const COLLAPSE_KEY = "metrion.sidebar.collapsed";

/** What a page's header needs from the frame around it. Present only inside a `ShellFrame`. */
export const FrameContext = createContext<{ openMenu: () => void } | null>(null);

/** The signed-in app frame that STAYS MOUNTED while the seller moves between pages: the session gate, the notifications feed and the navigation.
 *
 * `app/dashboard/layout.tsx` renders it once, so a client-side navigation no longer tears the whole app down, shows a full-screen "Loading…" in place
 * of the sidebar, re-fetches the session, or makes the next page wait for that fetch before it starts its own requests. The notifications feed is
 * still refreshed on every navigation (as it was when the frame remounted), but in the background: the previous values stay on screen meanwhile.
 * `DashboardShell` (the per-page header and content) creates its own frame when it is used outside a layout, so nothing else has to change. */
export function ShellFrame({ children }: { children: ReactNode }) {
  // Idempotent: inside an existing frame (a layout AND a page both asking for one) it adds nothing, so the sidebar can never be doubled.
  return useContext(FrameContext) ? <>{children}</> : <OwnFrame>{children}</OwnFrame>;
}

function OwnFrame({ children }: { children: ReactNode }) {
  const { session, error, displayName, roleLabel } = useAppSession();
  const pathname = usePathname();
  const notifications = useNotificationsFeed(Boolean(session));
  const [collapsed, setCollapsed] = useState(false);
  // The drawer is open for ONE page: a navigation closes it without an effect (it used to close only because the whole frame remounted).
  const [drawerOpenAt, setDrawerOpenAt] = useState<string | null>(null);
  const mobileOpen = drawerOpenAt === pathname;
  // The CEO Hub is a full-screen workspace: the navigation is closed by default there (an overlay opened from the menu button in the hub's own header), at every width.
  const focusMode = pathname.startsWith("/dashboard/ceo-hub");
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  useSurfaceSheen(surfaceRef, Boolean(session) && !error); // the surface div only exists once the session has loaded

  // Restore the remembered collapse state after hydration (never during render: SSR has no storage).
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable (private mode): default expanded */
    }
  }, []);

  // Keep the badge and the feeds current as the seller moves around (stale-while-revalidate: `reload` does not blank what is shown).
  const reload = notifications.reload;
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    reload();
  }, [pathname, reload]);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  if (error) {
    return (
      <div role="alert" className="flex h-screen w-full items-center justify-center px-6 text-center" style={{ color: "var(--negative)" }}>
        {error}
      </div>
    );
  }
  if (!session) {
    return (
      <div role="status" className="flex h-screen w-full items-center justify-center" style={{ color: "var(--text-5)" }}>
        <span className="mt-spinner mr-2.5 inline-block h-4 w-4" aria-hidden />
        Loading…
      </div>
    );
  }

  return (
    <ShellProvider value={{ session, displayName, roleLabel, notifications }}>
      <FrameContext.Provider value={{ openMenu: () => setDrawerOpenAt(pathname) }}>
        <div ref={surfaceRef} className="mt-app-surface flex">
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-lg focus:px-3 focus:py-2 focus:text-sm"
            style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
          >
            Skip to content
          </a>
          <Sidebar
            userName={displayName}
            roleLabel={roleLabel}
            attentionCount={notifications.attentionCount}
            collapsed={collapsed && !focusMode}
            onToggleCollapsed={toggleCollapsed}
            mobileOpen={mobileOpen}
            onCloseMobile={() => setDrawerOpenAt(null)}
            overlay={focusMode}
          />
          {/* A visible edge handle for sliding the sidebar in and out (the same toggle as the Collapse button at the bottom of the sidebar). */}
          {!focusMode && <button
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            data-testid="sidebar-edge-toggle"
            className="mt-btn mt-focus fixed top-1/2 z-[75] hidden h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full transition-[left] duration-200 lg:flex"
            style={{ left: collapsed ? 62 : 226, background: "var(--bg-popover)", border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
          >
            <span style={{ display: "inline-flex", transform: collapsed ? "rotate(180deg)" : "none", transition: "transform 0.2s ease" }}>
              <Icon name="collapse" size={14} />
            </span>
          </button>}
          <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">{children}</div>
        </div>
      </FrameContext.Provider>
    </ShellProvider>
  );
}

export const useFrame = () => useContext(FrameContext);
