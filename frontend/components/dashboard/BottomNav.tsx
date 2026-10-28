"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { Icon } from "@/components/ui/Icon";
import { NAV_GROUPS, isActive } from "@/lib/navigation";

/** The five places a seller goes most, one tap away on a phone. The full menu stays behind the header button. Hidden from the desktop layout
 * and on the CEO Hub, whose chat bar owns the bottom of the screen. */
const IDS = ["overview", "cfo", "competitors", "products", "ceo-hub"];

export function BottomNav() {
  const pathname = usePathname();
  const hidden = pathname.startsWith("/dashboard/ceo-hub");
  useEffect(() => {
    if (hidden) return;
    document.documentElement.classList.add("mt-bottomnav");
    return () => document.documentElement.classList.remove("mt-bottomnav");
  }, [hidden]);
  if (hidden) return null;
  const items = IDS.map((id) => NAV_GROUPS.flatMap((g) => g.items).find((i) => i.id === id && i.href)).filter((i): i is NonNullable<typeof i> => !!i);
  return (
    <nav aria-label="Main" className="mt-bottomnav-bar">
      {items.map((i) => {
        const on = isActive(i, pathname);
        return (
          <Link key={i.id} href={i.href as string} aria-current={on ? "page" : undefined} data-on={on} className="mt-bottomnav-item mt-focus">
            <Icon name={i.icon} size={20} />
            <span>{i.id === "cfo" ? "Profit" : i.id === "ceo-hub" ? "CEO" : i.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
