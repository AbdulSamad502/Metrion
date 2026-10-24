import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Regression guard for an unexplained, one-off console error ("Maxim…") once seen on the Profit & Finance page at phone width during manual checks. It was not
// reproduced (14 further full tab sweeps in Chromium, sample data on and off). This pins what CAN be pinned: every tab renders and its period quick-picks work
// without React logging a single error (an update loop, a bad key, a hydration warning), with the backend failing every call.
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import CfoPage from "@/app/dashboard/cfo/tools/page";

let errors: unknown[][];
beforeEach(() => {
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...a) => { errors.push(a); });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/data-requests") || url.includes("/imports") ? [] : { detail: "down" }), { status: url.includes("/data-requests") || url.includes("/imports") ? 200 : 503, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Profit & Finance logs no React errors", () => {
  for (const tab of ["overview", "profitability", "cash", "gst", "anomalies", "import"]) {
    it(`renders the ${tab} tab and runs its period quick-picks cleanly`, async () => {
      window.history.replaceState(null, "", `/dashboard/cfo#${tab}`);
      render(<CfoPage />);
      const user = userEvent.setup();
      for (const b of screen.queryAllByRole("button", { name: "Last month" })) await user.click(b);
      await waitFor(() => expect(screen.getAllByRole("tab").length).toBe(6));
      expect(errors.map((e) => String(e[0]).slice(0, 120))).toEqual([]);
    });
  }
});
