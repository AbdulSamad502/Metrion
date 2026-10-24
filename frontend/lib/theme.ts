export type Theme = "dark" | "light";
const KEY = "metrion.theme";
const listeners = new Set<() => void>();

/** The seller's chosen theme for the signed-in app. Dark stays the default (the shipped look); light is opt-in and remembered in this browser only.
 * Storage may be unavailable (private mode), in which case the choice simply lasts for the visit. */
let current: Theme = "dark";
let loaded = false;

function load(): Theme {
  if (!loaded) {
    loaded = true;
    try {
      current = window.localStorage.getItem(KEY) === "light" ? "light" : "dark";
    } catch {
      /* storage unavailable: stay on the default */
    }
  }
  return current;
}

export const getTheme = (): Theme => load();
export const getServerTheme = (): Theme => "dark";

export function setTheme(next: Theme): void {
  load();
  current = next;
  try {
    window.localStorage.setItem(KEY, next);
  } catch {
    /* not remembered, still applied */
  }
  listeners.forEach((l) => l());
}

export function subscribeTheme(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Test seam: forget what was loaded so the next read hits storage again. */
export function resetThemeForTests(): void {
  loaded = false;
  current = "dark";
}
