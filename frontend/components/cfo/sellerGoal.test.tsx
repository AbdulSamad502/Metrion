import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SellerGoalSection } from "@/components/cfo/sections/ImportAndGoalSections";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const token = async () => "t";

let stored: { targetMarginPct: string | null; priorityCategory: string | null; note: string | null };
let calls: { method: string; body: unknown }[];
let putStatus: number;

beforeEach(() => {
  calls = [];
  putStatus = 200;
  stored = { targetMarginPct: null, priorityCategory: null, note: null };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, body });
    if (method === "PUT") {
      if (putStatus !== 200) return reply("financials.adjust permission required", putStatus);
      stored = { targetMarginPct: body.target_margin_pct, priorityCategory: body.priority_category, note: body.note };
      return reply({ manualAdjustmentId: "m1" });
    }
    return reply(stored);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Seller goal", () => {
  it("shows the goal that is already stored when it opens (so a saved goal is visible after a reload)", async () => {
    stored = { targetMarginPct: "18.50", priorityCategory: "reduce_fees", note: "festive" };
    render(<SellerGoalSection getToken={token} />);
    expect(await screen.findByTestId("current-goal")).toHaveTextContent("target margin 18.50% · priority reduce_fees · note festive");
  });

  it("says plainly when nothing is saved", async () => {
    render(<SellerGoalSection getToken={token} />);
    expect(await screen.findByText("No goal is saved yet.")).toBeInTheDocument();
  });

  it("saves, then confirms by reading it back from the server", async () => {
    render(<SellerGoalSection getToken={token} />);
    const user = userEvent.setup();
    await screen.findByText("No goal is saved yet.");
    await user.type(screen.getByLabelText(/Target margin/), "15.5");
    await user.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByTestId("current-goal")).toHaveTextContent("target margin 15.5%");
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    expect(calls.map((c) => c.method)).toEqual(["GET", "PUT", "GET"]);
    expect(calls[1].body).toEqual({ target_margin_pct: "15.5", priority_category: null, note: null });
  });

  it("refuses a margin that is not a percentage and sends nothing", async () => {
    render(<SellerGoalSection getToken={token} />);
    const user = userEvent.setup();
    await screen.findByText("No goal is saved yet.");
    for (const bad of ["abc", "150", "-5", "15%"]) {
      await user.clear(screen.getByLabelText(/Target margin/));
      await user.type(screen.getByLabelText(/Target margin/), bad);
      await user.click(screen.getByRole("button", { name: "Save goal" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/between 0 and 100/);
    }
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });

  it("a refused save is shown in words, never as Saved, and the stored goal is unchanged", async () => {
    putStatus = 403;
    render(<SellerGoalSection getToken={token} />);
    const user = userEvent.setup();
    await screen.findByText("No goal is saved yet.");
    await user.type(screen.getByLabelText(/Target margin/), "15");
    await user.click(screen.getByRole("button", { name: "Save goal" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/);
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.getByText("No goal is saved yet.")).toBeInTheDocument();
  });
});
