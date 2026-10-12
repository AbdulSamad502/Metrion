import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const failWith = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })));

describe("Competitor workspace load errors", () => {
  it("shows plain wording for a 403 and never the raw payload", async () => {
    failWith(403, { detail: { code: "NOT_PERMITTED", internal: "stack at /srv/app.py:12" } });
    render(<CompetitorWorkspace />);
    expect(await screen.findByText(/do not have permission/i)).toBeInTheDocument();
    expect(screen.queryByText(/stack at|NOT_PERMITTED/)).toBeNull();
  });

  it("shows the not-set-up wording for a 503", async () => {
    failWith(503, { detail: { code: "CONFIG_MISSING" } });
    render(<CompetitorWorkspace />);
    expect(await screen.findByText(/not set up on the server yet/i)).toBeInTheDocument();
  });

  it("announces a failed load as an alert so assistive technology reads it", async () => {
    failWith(503, { detail: { code: "CONFIG_MISSING" } });
    render(<CompetitorWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not set up on the server yet/i);
  });
});
