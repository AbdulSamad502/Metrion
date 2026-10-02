"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { FOOTER_NAV, NAV_GROUPS, isActive } from "@/lib/navigation";
import { ShellProvider } from "@/lib/ShellContext";
import { useAppSession } from "@/lib/useAppSession";
import { useNotificationsFeed } from "@/lib/useNotifications";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

const COLLAPSE_KEY = "metrion.sidebar.collapsed";

/** The signed-in app frame every dashboard page renders inside: session gate, persistent
 * navigation, page header and a scrolling content region. It loads the session and the
 * notifications feed ONCE and shares them via `useShell()`, so a page's own body only mounts
 * (and only starts fetching) after the user is known. */
export function DashboardShell({
  title,
  subtitle,
  context,
  actions,
  children,
}: {
  title: string;
  subtitle: string;
  /** Header-centre content; omit unless it is genuinely useful on this page. */
  context?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { session, error, displayName, roleLabel } = useAppSession();
  const pathname = usePathname();
  const eyebrow =
    NAV_GROUPS.find((g) => g.items.some((i) => isActive(i, pathname)))?.label ??
    (FOOTER_NAV.some((i) => isActive(i, pathname)) ? "Workspace" : undefined);
  const notifications = useNotificationsFeed(Boolean(session));
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Restore the remembered collapse state after hydration (never during render: SSR has no storage).
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable (private mode) — default expanded */
    }
  }, []);

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
      <div className="mt-app-surface flex">
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
          collapsed={collapsed}
          onToggleCollapsed={toggleCollapsed}
          mobileOpen={mobileOpen}
          onCloseMobile={() => setMobileOpen(false)}
        />
        <div className="flex h-screen min-w-0 flex-1 flex-col overflow-hidden">
          <Topbar
            title={title}
            subtitle={subtitle}
            eyebrow={eyebrow}
            attentionCount={notifications.attentionCount}
            onOpenMenu={() => setMobileOpen(true)}
            context={context}
            actions={actions}
            showCeoShortcut={!pathname.startsWith("/dashboard/ceo-hub")}
          />
          <main id="main" tabIndex={-1} className="flex-1 overflow-y-auto px-4 py-6 outline-none sm:px-8 sm:py-8">
            {children}
          </main>
        </div>
      </div>
    </ShellProvider>
  );
}
