"use client";

import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { ShellProvider } from "@/lib/ShellContext";
import { useAppSession } from "@/lib/useAppSession";
import { useNotificationsFeed } from "@/lib/useNotifications";
import { getServerTheme, getTheme, subscribeTheme } from "@/lib/theme";
import { useSurfaceSheen } from "@/lib/useSurfaceSheen";
import { Sidebar } from "./Sidebar";
import { Icon } from "@/components/ui/Icon";
import { ToastProvider } from "@/components/ui/Toast";
import { DemoBadge } from "@/components/demo/DemoBadge";
import "./typography.css";
import "./layered.css";
import "./interaction.css";

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
  // The chosen theme applies to the signed-in app only, and never to the CEO Hub, which keeps its own dark canvas.
  const chosen = useSyncExternalStore(subscribeTheme, getTheme, getServerTheme);
  const theme = focusMode ? "dark" : chosen;
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    return () => {
      delete root.dataset.theme; // marketing and sign-in pages are always dark
    };
  }, [theme]);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  useSurfaceSheen(surfaceRef, false); // the cursor-following glow on cards is switched off; nothing glows under the pointer // the surface div only exists once the session has loaded

  // The app reads as a browser at 80%: on a desktop-width window everything is drawn at four-fifths size (see .mt-zoom in sidebar.css).
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.classList.add("mt-zoom", "mt-dash-type");
    return () => root.classList.remove("mt-zoom", "mt-dash-type");
  }, []);

  // Layered surfaces (deep page, lighter cards; see layered.css) on every dashboard page except the CEO Hub, which keeps its own look.
  // To switch the treatment off, delete layered.css, its import above and this effect.
  useLayoutEffect(() => {
    const root = document.documentElement;
    if (focusMode) return;
    root.dataset.surface = "layered";
    return () => { delete root.dataset.surface; };
  }, [focusMode]);

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
      <ToastProvider>
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
          <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">{children}</div>
          <DemoBadge />
        </div>
      </FrameContext.Provider>
      </ToastProvider>
    </ShellProvider>
  );
}

export const useFrame = () => useContext(FrameContext);
