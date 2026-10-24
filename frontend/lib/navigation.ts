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

/** What each page is called and what it is for, in plain words. The navigation labels ARE these titles (same constants), so a menu entry and the page it
 * opens can never disagree. Internal role names (CFO, CMO, CEO) belong inside the pages that explain them, not in the menu or the headings. */
export const PAGE_COPY = {
  overview: { title: "Overview", subtitle: "Your business today" },
  "ceo-hub": { title: "CEO Hub", subtitle: "Ask in plain words. Metrion answers from your data, or hands the question to the right specialist." },
  notifications: { title: "Action Center", subtitle: "What needs you" },
  products: { title: "Products", subtitle: "Product ideas and suppliers" },
  competitors: { title: "Competitors", subtitle: "Prices, changes and what customers say" },
  "pnl-calculator": { title: "Profit Calculator", subtitle: "Try prices, costs and fees before you commit. A what-if from the numbers you type, never your verified results" },
  cfo: { title: "Profit & Finance", subtitle: "Profit and where money leaks" },
  cmo: { title: "Listings & Marketing", subtitle: "Titles and listing copy to copy" },
  agents: { title: "Agents", subtitle: "Your specialists" },
  settings: { title: "Settings", subtitle: "Account, business and alerts" },
} as const satisfies Record<string, { title: string; subtitle: string }>;

const label = (id: keyof typeof PAGE_COPY) => PAGE_COPY[id].title;

/** The full browser-tab title. Complete in every route segment (no template): Next applied a parent's title template inconsistently on client navigation. */
export const pageTitle = (id: keyof typeof PAGE_COPY): string => `${PAGE_COPY[id].title} · Metrion`;

/** Start: where a seller begins. Business: the four workspaces, in the order a seller thinks about them (what to sell, who competes, what it earns,
 * how to list it). System sits below (`FOOTER_NAV`). */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Start",
    items: [
      { id: "overview", label: label("overview"), icon: "overview", href: "/dashboard", exact: true },
      { id: "ceo-hub", label: label("ceo-hub"), icon: "ceo", href: "/dashboard/ceo-hub" },
      { id: "notifications", label: label("notifications"), icon: "notifications", href: "/dashboard/notifications" },
    ],
  },
  {
    label: "Business",
    items: [
      { id: "products", label: label("products"), icon: "products", href: "/dashboard/pi" },
      { id: "competitors", label: label("competitors"), icon: "competitors", href: "/dashboard/competitors" },
      { id: "cfo", label: label("cfo"), icon: "finance", href: "/dashboard/cfo" },
      { id: "pnl-calculator", label: label("pnl-calculator"), icon: "reports", href: "/dashboard/pnl-calculator" },
      { id: "cmo", label: label("cmo"), icon: "marketing", href: "/dashboard/cmo" },
    ],
  },
];

export const SYSTEM_GROUP_LABEL = "System";

/** "Agent Cart" is deliberately not listed: there is no purchasing or entitlement service yet (the Agents page says so in words),
 * and an inert nav entry would only look like a feature. */
export const FOOTER_NAV: NavItem[] = [
  { id: "agents", label: label("agents"), icon: "agents", href: "/dashboard/agents" },
  { id: "settings", label: label("settings"), icon: "settings", href: "/settings" },
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
