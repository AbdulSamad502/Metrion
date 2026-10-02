import type { IconName } from "@/components/ui/Icon";

/** The app's navigation model (docs/design/frontend-design): three groups plus a footer block.
 * An item with no `href` is not a real page yet and renders as inert "Soon" chrome — it is never
 * wired to a fake screen. `match` decides which items the current pathname highlights. */
export type NavItem = {
  id: string;
  label: string;
  icon: IconName;
  href?: string;
  soon?: boolean;
  /** Pathname prefixes that count as "inside" this item (defaults to `href`). */
  match?: string[];
  exact?: boolean;
};

export type NavGroup = { label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Profit Intelligence",
    items: [
      { id: "overview", label: "Overview", icon: "overview", href: "/dashboard", exact: true },
      { id: "ceo-hub", label: "CEO Hub", icon: "ceo", href: "/dashboard/ceo-hub" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { id: "products", label: "Products", icon: "products", href: "/dashboard/pi" },
      { id: "competitors", label: "Competitors", icon: "competitors", href: "/dashboard/competitors" },
      { id: "cfo", label: "CFO", icon: "finance", href: "/dashboard/cfo" },
    ],
  },
];

export const FOOTER_NAV: NavItem[] = [
  { id: "agents", label: "Agents", icon: "agents", href: "/dashboard/agents" },
  { id: "cart", label: "Agent Cart", icon: "cart", soon: true },
  { id: "settings", label: "Settings", icon: "settings", href: "/settings" },
  { id: "notifications", label: "Notifications", icon: "notifications", href: "/dashboard/notifications" },
];

export function isActive(item: NavItem, pathname: string): boolean {
  if (!item.href) return false;
  if (item.exact) return pathname === item.href;
  const prefixes = item.match ?? [item.href];
  return prefixes.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function allNavItems(): NavItem[] {
  return [...NAV_GROUPS.flatMap((g) => g.items), ...FOOTER_NAV];
}
