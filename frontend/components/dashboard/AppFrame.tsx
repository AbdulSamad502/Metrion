"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ShellFrame } from "./ShellFrame";

/** The signed-in app's routes. A new app route that is missing here still works (its `DashboardShell` creates its own frame); it only loses
 * the persistent frame, i.e. it remounts when the seller crosses to or from it. */
const APP_PREFIXES = ["/dashboard", "/settings"];
export const isAppPath = (pathname: string | null): boolean =>
  !!pathname && APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));

/** Keeps ONE `ShellFrame` mounted across every signed-in page, Settings included. Settings sits outside `/dashboard`, so a per-segment layout cannot
 * span both; without this, moving between them replaced the whole app (full-screen "Loading…", a new session fetch) and dropped keyboard focus to
 * the page body. Marketing and auth pages are left unwrapped. Rendered once, in the root layout. */
export function AppFrame({ children }: { children: ReactNode }) {
  return isAppPath(usePathname()) ? <ShellFrame>{children}</ShellFrame> : <>{children}</>;
}
