import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CmoWorkspace } from "@/components/cmo/CmoWorkspace";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
let titleResponse: () => Promise<Response>;
let titleCalls: unknown[];
beforeEach(() => {
  titleCalls = [];
  window.history.replaceState(null, "", "/dashboard/cmo");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/v1/cmo/title-sets")) { titleCalls.push(JSON.parse(String(init?.body))); return titleResponse(); }
    return reply({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function reachTitles() {
  const user = userEvent.setup();
  render(<CmoWorkspace />);
  const next = screen.getByRole("button", { name: "Continue to titles" });
  expect(next).toBeDisabled(); // nothing is defaulted: no product and no marketplace yet
  expect(screen.getByText("Choose at least one marketplace.")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Product name"), "Steel water bottle");
  await user.click(screen.getByRole("checkbox", { name: "Amazon" }));
  await user.click(screen.getByRole("button", { name: "Continue to titles" }));
  return user;
}

describe("CMO title generation (the supported route now that chat refuses it)", () => {
  it("needs a product and a marketplace before it will continue", async () => {
    await reachTitles();
    expect(screen.getByRole("button", { name: "Write title options" })).toBeEnabled();
  });

  it("shows pending, sends exactly what was entered, and reports units only after a successful response", async () => {
    let finish!: (r: Response) => void;
    titleResponse = () => new Promise((res) => { finish = res; });
    const user = await reachTitles();
    await user.click(screen.getByRole("button", { name: "Write title options" }));
    expect(await screen.findByText(/Writing titles for each marketplace/)).toBeInTheDocument();
    expect(screen.queryByText(/units? used/)).toBeNull();
    finish(reply({ runStatus: "COMPLETE", unitsBilled: 1, artefacts: [] }));
    expect(await screen.findByText("1 unit used")).toBeInTheDocument();
    expect(titleCalls).toHaveLength(1);
    expect(JSON.stringify(titleCalls[0])).toContain("Steel water bottle");
  });

  it("a plan-limit failure says nothing was run or charged, shows no units, and Try again recovers", async () => {
    titleResponse = async () => reply({ code: "OVER_CAP", remaining: 0, meterCode: "cmo.generate_title_sets" }, 402);
    const user = await reachTitles();
    await user.click(screen.getByRole("button", { name: "Write title options" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/plan limit/i);
    expect(alert).toHaveTextContent(/Nothing was run or charged/);
    expect(screen.queryByText(/units? used/)).toBeNull();
    titleResponse = async () => reply({ runStatus: "COMPLETE", unitsBilled: 1, artefacts: [] });
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("1 unit used")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("an unconfigured server is shown as 'not set up' and never as a result", async () => {
    titleResponse = async () => reply({ code: "CONFIG_MISSING", missing: ["CMO_LLM_TIMEOUT_SECONDS"] }, 503);
    const user = await reachTitles();
    await user.click(screen.getByRole("button", { name: "Write title options" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Not set up yet/);
    expect(screen.queryByText(/units? used/)).toBeNull();
    expect(screen.queryByText(/title request/)).toBeNull(); // no result card of any kind
  });
});
