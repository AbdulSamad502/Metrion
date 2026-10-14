"use client";

import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { FOOTER_NAV, NAV_GROUPS, SYSTEM_GROUP_LABEL, isActive } from "@/lib/navigation";
import { useShell } from "@/lib/ShellContext";
import { ShellFrame, useFrame } from "./ShellFrame";
import { Topbar } from "./Topbar";

type ShellProps = {
  title: string;
  subtitle: string;
  /** Header-centre content; omit unless it is genuinely useful on this page. */
  context?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
};

/** The page header and scrolling content region of a signed-in page. The session, the notifications feed and the navigation come from the
 * `ShellFrame` around it (`app/dashboard/layout.tsx` keeps one mounted across pages); outside a layout this creates its own frame, so a page
 * (Settings, a test) works the same either way. Pages read the session and notifications through `useShell()`, so a page's own body only mounts
 * (and only starts fetching) after the user is known. */
export function DashboardShell(props: ShellProps) {
  const frame = useFrame();
  const page = <ShellPage {...props} />;
  return frame ? page : <ShellFrame>{page}</ShellFrame>;
}

function ShellPage({ title, subtitle, context, actions, children }: ShellProps) {
  const { notifications } = useShell();
  const frame = useFrame();
  const pathname = usePathname();
  const eyebrow =
    NAV_GROUPS.find((g) => g.items.some((i) => isActive(i, pathname)))?.label ??
    (FOOTER_NAV.some((i) => isActive(i, pathname)) ? SYSTEM_GROUP_LABEL : undefined);
  // The browser tab and the screen-reader route announcement name the page; without this every page was just "Metrion".
  useEffect(() => {
    document.title = `${title} · Metrion`;
  }, [title]);
  // The CEO Hub is a full-screen workspace: no page header (the page name stays available to screen readers) and no page padding.
  const fullBleed = pathname.startsWith("/dashboard/ceo-hub");
  return (
    <>
      {fullBleed ? (
        <h1 className="sr-only">{title}</h1>
      ) : (
        <Topbar
          title={title}
          subtitle={subtitle}
          eyebrow={eyebrow}
          attentionCount={notifications.attentionCount}
          onOpenMenu={() => frame?.openMenu()}
          context={context}
          actions={actions}
          showCeoShortcut
        />
      )}
      <main
        id="main"
        tabIndex={-1}
        className={`min-h-0 flex-1 overflow-y-auto outline-none ${fullBleed ? "p-3 sm:p-4 xl:overflow-hidden" : "px-4 py-6 sm:px-8 sm:py-8"}`}
      >
        {children}
      </main>
    </>
  );
}
