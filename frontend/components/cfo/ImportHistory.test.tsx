import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ImportHistory } from "@/components/cfo/ImportHistory";

const failing = (status: number, detail: unknown) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } })));
};

describe("Import history errors", () => {
  it("shows plain wording and never the raw payload", async () => {
    failing(403, { code: "NOT_PERMITTED", trace: "at /srv/app.py:12" });
    render(<ImportHistory getToken={async () => "t"} refreshTick={0} lastUpload={null} />);
    expect(await screen.findByText(/do not have permission/i)).toBeInTheDocument();
    expect(screen.queryByText(/NOT_PERMITTED|app\.py/)).toBeNull();
    vi.unstubAllGlobals();
    expect(new ApiError(500, "x").status).toBe(500);
  });
});
