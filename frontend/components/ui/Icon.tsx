import type { ReactNode } from "react";

/** Line icons for the app shell — the exact 20x20 glyphs from docs/design/frontend-design's
 * navigation, plus the few utility glyphs the dashboard needs. `currentColor` so a parent's
 * text color (active / hover / locked) drives the icon. Decorative by default (aria-hidden);
 * pass `label` when an icon stands alone. */
export type IconName = "overview" | "ceo" | "products" | "competitors" | "orders" | "customers" | "finance" | "marketing" | "reports" | "tag" | "store" | "returns" | "target" | "agents" | "cart" | "settings" | "notifications" | "lock" | "check" | "plus" | "arrow" | "chevron" | "close" | "menu" | "collapse" | "logout" | "dot" | "alert" | "trash" | "sun" | "moon";

const PATHS: Record<IconName, ReactNode> = {
  overview: <><rect x="2" y="2" width="7" height="7" rx="1.5" /><rect x="11" y="2" width="7" height="7" rx="1.5" /><rect x="2" y="11" width="7" height="7" rx="1.5" /><rect x="11" y="11" width="7" height="7" rx="1.5" /></>,
  ceo: <><circle cx="10" cy="4" r="1.8" /><circle cx="4" cy="14" r="1.8" /><circle cx="16" cy="14" r="1.8" /><circle cx="10" cy="17.3" r="1.5" fill="currentColor" stroke="none" /><line x1="10" y1="5.8" x2="6" y2="12.4" /><line x1="10" y1="5.8" x2="14" y2="12.4" /><line x1="6" y1="14" x2="10" y2="16.3" /><line x1="14" y1="14" x2="10" y2="16.3" /></>,
  products: <><path d="M10 2 L17 5.5 V14.5 L10 18 L3 14.5 V5.5 Z" /><path d="M3 5.5 L10 9 L17 5.5" /><line x1="10" y1="9" x2="10" y2="18" /></>,
  competitors: <><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.8" /><circle cx="10" cy="10" r="0.9" fill="currentColor" stroke="none" /></>,
  orders: <><path d="M3 4 H5 L7 13 H15 L17 6 H6" /><circle cx="8" cy="17" r="1.3" fill="currentColor" stroke="none" /><circle cx="14" cy="17" r="1.3" fill="currentColor" stroke="none" /></>,
  customers: <><circle cx="7.5" cy="6.5" r="2.6" /><path d="M2.5 16 C2.5 12.5 5 11 7.5 11 C10 11 12.5 12.5 12.5 16" /><circle cx="14.5" cy="7.5" r="2.1" /><path d="M13 11.2 C15.5 11.4 17.5 12.8 17.5 16" /></>,
  finance: <><rect x="2" y="5" width="16" height="11" rx="2" /><path d="M2 8 H18" /><circle cx="14" cy="12" r="1.3" fill="currentColor" stroke="none" /></>,
  marketing: <><path d="M2 9 H6 L13 4 V16 L6 11 H2 Z" /><path d="M6 11 L7 16" /></>,
  reports: <><line x1="3" y1="17" x2="17" y2="17" /><rect x="4" y="10" width="3" height="7" /><rect x="8.5" y="6" width="3" height="11" /><rect x="13" y="12" width="3" height="5" /></>,
  tag: <><path d="M3 3 H10.5 L17 9.5 L10.5 16 L4 9.5 Z" /><circle cx="7" cy="7" r="1.2" fill="currentColor" stroke="none" /></>,
  store: <><path d="M3 8 L4.5 3 H15.5 L17 8" /><path d="M3 8 C3 9.7 4.2 10.5 5.5 10.5 C6.8 10.5 8 9.7 8 8 C8 9.7 9 10.5 10 10.5 C11 10.5 12 9.7 12 8 C12 9.7 13.2 10.5 14.5 10.5 C15.8 10.5 17 9.7 17 8" /><path d="M4.5 10.5 V17 H15.5 V10.5" /><path d="M8.5 17 V13 H11.5 V17" /></>,
  returns: <><path d="M4 9 C4 5.7 6.7 3.5 10 3.5 C12.3 3.5 14.3 4.6 15.4 6.4" /><path d="M16 3 V6.8 H12.2" /><path d="M16 11 C16 14.3 13.3 16.5 10 16.5 C7.7 16.5 5.7 15.4 4.6 13.6" /><path d="M4 17 V13.2 H7.8" /></>,
  target: <><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.6" /><circle cx="10" cy="10" r="0.9" fill="currentColor" stroke="none" /></>,
  agents: <><rect x="4" y="6" width="12" height="10" rx="2.5" /><circle cx="7.6" cy="11" r="1.15" fill="currentColor" stroke="none" /><circle cx="12.4" cy="11" r="1.15" fill="currentColor" stroke="none" /><line x1="10" y1="6" x2="10" y2="3.2" /><circle cx="10" cy="2.4" r="1" fill="currentColor" stroke="none" /></>,
  cart: <><circle cx="7" cy="17" r="1.3" fill="currentColor" stroke="none" /><circle cx="14" cy="17" r="1.3" fill="currentColor" stroke="none" /><path d="M2 3 H4 L6.5 13 H15.5 L17.5 6 H5.5" /></>,
  settings: <><circle cx="10" cy="10" r="6.2" /><circle cx="10" cy="10" r="2" fill="currentColor" stroke="none" /><line x1="10" y1="1.8" x2="10" y2="3.6" /><line x1="10" y1="16.4" x2="10" y2="18.2" /><line x1="1.8" y1="10" x2="3.6" y2="10" /><line x1="16.4" y1="10" x2="18.2" y2="10" /></>,
  notifications: <><path d="M10 2.5 C7 2.5 5.5 4.8 5.5 8 V11 L4 13.5 H16 L14.5 11 V8 C14.5 4.8 13 2.5 10 2.5 Z" /><path d="M8.2 15.5 C8.2 16.6 9 17.5 10 17.5 C11 17.5 11.8 16.6 11.8 15.5" /></>,
  lock: <><rect x="4.5" y="9" width="11" height="8" rx="1.5" /><path d="M6.5 9 V6.5 C6.5 4.3 8 3 10 3 C12 3 13.5 4.3 13.5 6.5 V9" /></>,
  check: <><circle cx="10" cy="10" r="8" /><path d="M6.3 10.2 L8.8 12.7 L13.7 7.3" /></>,
  plus: <><line x1="10" y1="3" x2="10" y2="17" /><line x1="3" y1="10" x2="17" y2="10" /></>,
  arrow: <><line x1="3" y1="10" x2="16" y2="10" /><path d="M11 5 L16 10 L11 15" /></>,
  chevron: <><path d="M5 7.5 L10 12.5 L15 7.5" /></>,
  close: <><line x1="5" y1="5" x2="15" y2="15" /><line x1="15" y1="5" x2="5" y2="15" /></>,
  menu: <><line x1="3" y1="6" x2="17" y2="6" /><line x1="3" y1="10" x2="17" y2="10" /><line x1="3" y1="14" x2="17" y2="14" /></>,
  collapse: <><path d="M12 5 L7 10 L12 15" /></>,
  logout: <><path d="M8 3H5a1.5 1.5 0 0 0-1.5 1.5v11A1.5 1.5 0 0 0 5 17h3" /><path d="M13 14l4-4-4-4" /><path d="M17 10H7.5" /></>,
  sun: <><circle cx="10" cy="10" r="3.4" /><path d="M10 2.5 V4.2 M10 15.8 V17.5 M2.5 10 H4.2 M15.8 10 H17.5 M4.7 4.7 L5.9 5.9 M14.1 14.1 L15.3 15.3 M4.7 15.3 L5.9 14.1 M14.1 5.9 L15.3 4.7" /></>,
  moon: <><path d="M16.5 11.6 A6.7 6.7 0 1 1 8.4 3.5 A5.4 5.4 0 0 0 16.5 11.6 Z" /></>,
  dot: <><circle cx="10" cy="10" r="3" fill="currentColor" stroke="none" /></>,
  trash: <><path d="M4 6 H16" /><path d="M8 6 V4 H12 V6" /><path d="M5.5 6 L6.3 16.5 H13.7 L14.5 6" /><line x1="8.5" y1="9" x2="8.5" y2="14" /><line x1="11.5" y1="9" x2="11.5" y2="14" /></>,
  alert: <><circle cx="10" cy="10" r="8" /><line x1="10" y1="6" x2="10" y2="10.6" /><circle cx="10" cy="13.6" r="0.9" fill="currentColor" stroke="none" /></>,
};

export function Icon({
  name,
  size = 18,
  strokeWidth = 1.6,
  label,
  className,
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  label?: string;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={[name === "arrow" ? "mt-arrow" : null, className].filter(Boolean).join(" ") || undefined}
      style={{ flexShrink: 0 }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {PATHS[name]}
    </svg>
  );
}
