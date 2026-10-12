import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LandedCostSection } from "@/components/cfo/sections/PricingSections";
import { DataRequestNote } from "@/components/cfo/DataRequestNote";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const token = async () => "t";
const REQ = "7c1d3e50-0000-4000-8000-0000000000aa";
let requests: object[];
let listStatus: number;
beforeEach(() => {
  listStatus = 200;
  requests = [{ id: REQ, requestedField: "supplier.quote", reason: "No active quote exists for SKU-1.", blockingMetric: "LANDED_COST", status: "OPEN", createdAt: "2026-10-11T00:00:00Z" }];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (String(url).endsWith("/api/v1/cfo/data-requests")) return listStatus === 200 ? reply(requests) : reply("down", listStatus);
    if (String(url).endsWith("/api/v1/cfo/landed-cost")) return reply({ result: null, dataRequestId: REQ });
    return reply({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("what a missing input says", () => {
  it("names what is missing, says nothing was assumed, and says where to give it", async () => {
    render(<DataRequestNote id={REQ} getToken={token} />);
    const note = await screen.findByText(/Metrion needs a supplier quote for this product/);
    expect(note.closest("[data-testid]")).toHaveTextContent(/No active quote exists for SKU-1\. Nothing was assumed\. Tell Ask Metrion what you have/);
    expect(screen.getByRole("link", { name: "Ask Metrion" })).toHaveAttribute("href", "/dashboard/ceo-hub");
  });

  it("promises no way to supply a field Ask Metrion cannot save", async () => {
    requests = [{ id: REQ, requestedField: "fee_reference", reason: "No fee row covers AMAZON / Home.", blockingMetric: "PRICING", status: "OPEN", createdAt: "2026-10-11T00:00:00Z" }];
    render(<DataRequestNote id={REQ} getToken={token} />);
    expect(await screen.findByText(/Metrion needs fee_reference\. No fee row covers AMAZON \/ Home\. Nothing was assumed\./)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ask Metrion" })).toBeNull();
  });

  it("still tells the seller an input is missing when the request cannot be read back", async () => {
    listStatus = 503;
    render(<DataRequestNote id={REQ} getToken={token} />);
    expect(await screen.findByTestId("data-request-note")).toHaveTextContent(/an input is missing \(request 7c1d3e50\)\. Nothing was assumed\./);
  });

  it("Landed cost shows it instead of a bare id", async () => {
    render(<LandedCostSection getToken={token} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("SKU"), "SKU-1");
    await user.type(screen.getByLabelText("Supplier quote target ref"), "SKU-1");
    await user.type(screen.getByLabelText("Quantity"), "100");
    await user.click(screen.getByRole("button", { name: "Compute landed cost" }));
    expect(await screen.findByText(/Metrion needs a supplier quote for this product/)).toBeInTheDocument();
    expect(screen.queryByText(/data request raised/i)).toBeNull();
  });
});
