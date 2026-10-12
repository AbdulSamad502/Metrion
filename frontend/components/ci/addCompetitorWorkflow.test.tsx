import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
let posts: unknown[];
let postResponse: () => Promise<Response>;
let listed: unknown[];
beforeEach(() => {
  posts = []; listed = [];
  window.history.replaceState(null, "", "/dashboard/competitors");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/v1/ci/competitor-urls") && init?.method === "POST") { posts.push(JSON.parse(String(init.body))); return postResponse(); }
    if (url.endsWith("/api/v1/ci/competitor-urls")) return reply(listed);
    return reply({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Competitors: add a tracked URL", () => {
  it("names both inputs and refuses an empty URL without calling the backend", async () => {
    render(<CompetitorWorkspace />);
    expect(await screen.findByLabelText("Competitor product URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Link to SKU (optional)")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the competitor's product URL first.");
    expect(posts).toHaveLength(0);
  });

  it("shows a pending state that blocks a double submit, then clears the form only on success", async () => {
    let finish!: (r: Response) => void;
    postResponse = () => new Promise((res) => { finish = res; });
    render(<CompetitorWorkspace />);
    const url = await screen.findByLabelText("Competitor product URL");
    const user = userEvent.setup();
    await user.type(url, "https://amazon.in/dp/B0TEST");
    await user.click(screen.getByRole("button", { name: "Add" }));
    const busy = await screen.findByRole("button", { name: "Adding…" });
    expect(busy).toBeDisabled();
    await user.click(busy);
    expect(posts).toHaveLength(1); // one request, never two
    expect(url).toHaveValue("https://amazon.in/dp/B0TEST"); // not cleared before success
    listed = [{ id: "u1", url: "https://amazon.in/dp/B0TEST", label: null, linkedSku: null, tags: [], status: "ACTIVE" }];
    finish(reply({ id: "u1" }));
    await waitFor(() => expect(url).toHaveValue(""));
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a failed add keeps what was typed, is announced in plain words, and can be retried", async () => {
    postResponse = async () => reply({ code: "NOT_PERMITTED", trace: "at /srv/ci.py:3" }, 403);
    render(<CompetitorWorkspace />);
    const url = await screen.findByLabelText("Competitor product URL");
    const user = userEvent.setup();
    await user.type(url, "https://amazon.in/dp/B0TEST");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
    expect(screen.queryByText(/ci\.py|NOT_PERMITTED/)).toBeNull();
    expect(url).toHaveValue("https://amazon.in/dp/B0TEST");
    postResponse = async () => reply({ id: "u1" });
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(url).toHaveValue(""));
    expect(posts).toHaveLength(2);
  });
});
