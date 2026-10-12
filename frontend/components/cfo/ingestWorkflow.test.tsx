import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IngestUploadSection } from "@/components/cfo/sections/ImportAndGoalSections";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
let response: () => Promise<Response>;
let calls: { url: string; hasFile: boolean }[];
let uploaded: unknown[];

beforeEach(() => {
  calls = []; uploaded = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), hasFile: (init?.body as FormData | undefined)?.get?.("file") instanceof File });
    return response();
  }));
});
afterEach(() => vi.unstubAllGlobals());

const mount = () => render(<IngestUploadSection getToken={async () => "t"} onUploaded={(o) => uploaded.push(o)} />);
const csv = () => new File(["a,b\n1,2"], "orders.csv", { type: "text/csv" });
const pick = async (user: ReturnType<typeof userEvent.setup>) => user.upload(screen.getByLabelText("File"), csv());

describe("CFO import: upload a marketplace report", () => {
  it("asks for a file first and calls nothing without one", async () => {
    mount();
    await userEvent.setup().click(screen.getByRole("button", { name: "Upload & ingest" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a CSV file first.");
    expect(calls).toHaveLength(0);
  });

  it("is pending while uploading and reports rows only after a successful response", async () => {
    let finish!: (r: Response) => void;
    response = () => new Promise((res) => { finish = res; });
    mount();
    const user = userEvent.setup();
    await pick(user);
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    expect(await screen.findByRole("button", { name: "Ingesting…" })).toBeDisabled();
    expect(screen.queryByRole("status")).toBeNull(); // nothing looks ingested yet
    finish(reply({ reportFileId: "r1", duplicate: false, rowCountAccepted: 9, rowCountRead: 10, rowCountRejected: 1 }));
    expect(await screen.findByRole("status")).toHaveTextContent(/Ingested\. 9 of 10 rows accepted/);
    expect(calls[0].url).toContain("/api/v1/cfo/ingest?marketplace=MEESHO&adapter_id=meesho.orders.v1");
    expect(calls[0].hasFile).toBe(true);
    expect(uploaded).toEqual([{ reportFileId: "r1", duplicate: false, filename: "orders.csv" }]);
  });

  it("says a duplicate file was not ingested again", async () => {
    response = async () => reply({ reportFileId: "r1", duplicate: true });
    mount();
    const user = userEvent.setup();
    await pick(user);
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/already imported — nothing was ingested again/);
  });

  it("a failed upload is plain words, never raw JSON or an exception, reports no success, and can be retried", async () => {
    response = async () => reply({ detail: { code: "ADAPTER_MISMATCH", trace: "at /srv/cfo.py:44" } }, 422);
    mount();
    const user = userEvent.setup();
    await pick(user);
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not valid/i);
    expect(screen.queryByText(/ADAPTER_MISMATCH|cfo\.py|\{/)).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(uploaded).toHaveLength(0);
    response = async () => reply({ reportFileId: "r2", duplicate: false, rowCountAccepted: 1, rowCountRead: 1, rowCountRejected: 0 });
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(uploaded).toHaveLength(1);
  });

  it("an unreadable server reply and a network failure are safe fallbacks", async () => {
    response = async () => new Response("<html>boom</html>", { status: 500 });
    mount();
    const user = userEvent.setup();
    await pick(user);
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent(/html|boom|Unexpected token/);
    response = async () => { throw new TypeError("Failed to fetch"); };
    await user.click(screen.getByRole("button", { name: "Upload & ingest" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not reach the server/)); // a lost connection says so, rather than a generic failure
  });
});
