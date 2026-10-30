"use client";

import { useLayoutEffect } from "react";

/** Sign-in, sign-up, forgot-password and onboarding have no light mode: clear any theme left on <html> by the dashboards. */
export function DarkOnly() {
  useLayoutEffect(() => { delete document.documentElement.dataset.theme; }, []);
  return null;
}
