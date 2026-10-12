import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GstLineAnalysisSection, GstLookupSection } from "@/components/cfo/sections/GstSections";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const token = async () => "t";

let calls: { path: string; body: unknown }[];
let next: () => Response;

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ path: String(url).replace(/^https?:\/\/[^/]+/, ""), body: init?.body ? JSON.parse(String(init.body)) : null });
    return next();
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function fillLine(user: ReturnType<typeof userEvent.setup>, ref: string, amount: string, rate = "") {
  await user.type(screen.getByPlaceholderText("line ref"), ref);
  await user.type(screen.getByPlaceholderText("listed ₹"), amount);
  if (rate) await user.type(screen.getByPlaceholderText("rate % (optional)"), rate);
  await user.type(screen.getByLabelText("As-of date"), "2026-09-30");
}

describe("GST line analysis", () => {
  it("sends the listed amount as exact paise", async () => {
    next = () => reply({ lines: [] });
    render(<GstLineAnalysisSection getToken={token} />);
    const user = userEvent.setup();
    await fillLine(user, "L1", "1,180.50", "18");
    await user.click(screen.getByRole("button", { name: "Analyze lines" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ lines: [{ line_ref: "L1", listed_paise: 118050, basis: "INCLUSIVE", rate_pct: "18" }], as_of_date: "2026-09-30" });
  });

  it.each([
    ["an unreadable amount", "abc", "", /Line 1 \("L1"\): the listed amount must be a rupee amount/],
    ["a rate with a % sign", "1180", "18%", /Line 1 \("L1"\): the rate must be a plain number/],
  ])("refuses %s before anything is sent, naming the line", async (_n, amount, rate, message) => {
    next = () => reply({ lines: [] });
    render(<GstLineAnalysisSection getToken={token} />);
    const user = userEvent.setup();
    await fillLine(user, "L1", amount, rate);
    await user.click(screen.getByRole("button", { name: "Analyze lines" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(calls).toHaveLength(0);
  });

  it("shows which field the server refused, instead of a generic 422", async () => {
    next = () => reply([{ loc: ["body", "lines", 0, "basis"], msg: "String should match pattern '^(INCLUSIVE|EXCLUSIVE)$'", type: "string_pattern_mismatch" }], 422);
    render(<GstLineAnalysisSection getToken={token} />);
    const user = userEvent.setup();
    await fillLine(user, "L1", "1180");
    await user.click(screen.getByRole("button", { name: "Analyze lines" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lines › item 1 › basis: String should match pattern/);
  });
});

describe("GST applicability lookup", () => {
  it("says plainly when the model that reads the tax pages could not be reached (503), and shows no result", async () => {
    next = () => reply("The model that reads GST pages could not be reached, so nothing was looked up. Try again shortly.", 503);
    render(<GstLookupSection getToken={token} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Product title/i), "Cotton bedsheet");
    await user.click(screen.getByRole("button", { name: /look up/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be reached, so nothing was looked up/);
    expect(screen.queryByText(/likely rate/i)).toBeNull();
  });
});
