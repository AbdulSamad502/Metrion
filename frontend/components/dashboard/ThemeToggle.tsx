"use client";

import { useSyncExternalStore } from "react";
import { Icon } from "@/components/ui/Icon";
import { getServerTheme, getTheme, setTheme, subscribeTheme } from "@/lib/theme";

/** One switch between the dark and light look. It names the theme you would switch TO, and reports the current one to assistive technology. */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getTheme, getServerTheme);
  const light = theme === "light";
  return (
    <button
      type="button"
      onClick={() => setTheme(light ? "dark" : "light")}
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
      aria-pressed={light}
      title={light ? "Dark theme" : "Light theme"}
      className="mt-btn mt-focus flex h-10 w-10 items-center justify-center rounded-xl"
      style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}
    >
      <Icon name={light ? "moon" : "sun"} size={17} />
    </button>
  );
}
