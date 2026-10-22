import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MappingReview } from "@/components/cfo/v2/data/MappingReview";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "tok" }) }));

const JOB = "11111111-1111-4111-8111-111111111111";
const mapping = {
  mappingId: "33333333-3333-4333-8333-333333333333", status: "PROPOSED", version: 1, reportKind: "SETTLEMENT", proposedBy: "MODEL:x", verified: false,
  fields: [
    { index: 0, sourceColumn: "Order ID", canonicalField: "order_ref", componentCode: null, transform: null, taxInclusion: null, signConvention: null, decision: "AUTO_ACCEPTED_BY_RULES", evidence: { errors: [], warnings: [], confirm_reasons: [] } },
    { index: 1, sourceColumn: "Sale Amount", canonicalField: "gross_item_amount", componentCode: null, transform: null, taxInclusion: "INCLUSIVE", signConvention: null, decision: "PENDING", evidence: { errors: [], warnings: [{ rule: "M-W1", message: "Looks like it includes tax" }], confirm_reasons: ["the amount may include GST"] } },
  ],
};
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

afterEach(() => vi.unstubAllGlobals());

describe("MappingReview", () => {
  it("shows each column, its evidence, the GST-inclusive heads-up BEFORE confirming, and requires an explicit confirmation", async () => {
    const sent: { url: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          sent.push({ url, body: JSON.parse(String(init.body)) });
          return reply({ ok: true }, 202);
        }
        return reply(mapping);
      }),
    );
    const onConfirmed = vi.fn();
    render(<MappingReview jobId={JOB} onConfirmed={onConfirmed} />);
    expect(await screen.findByText("Sale Amount", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Warning: Looks like it includes tax")).toBeInTheDocument();
    expect(screen.getByText(/cannot be used yet/)).toBeInTheDocument(); // the limitation is explained before confirm
    expect(screen.getByText("Please check: the amount may include GST")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("I confirm Sale Amount is read correctly"));
    await userEvent.click(screen.getByRole("button", { name: "Confirm these columns" }));
    expect(sent[0].url).toContain(`/api/v1/cfo/jobs/${JOB}/mapping/confirm`);
    expect(sent[0].body).toEqual({ decisions: { "1": "SELLER_CONFIRMED" }, overrides: {} });
    expect(onConfirmed).toHaveBeenCalled();
  });

  it("silence is not confirmation: nothing is pre-ticked, and a refusal lists every reason and changes nothing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_u: string, init?: RequestInit) =>
        init?.method === "POST" ? reply({ detail: { message: "The mapping cannot be confirmed yet.", reasons: ["column 'Sale Amount' needs your confirmation: the amount may include GST", "a required field is missing; map one of ['order_ref']"] } }, 422) : reply(mapping),
      ),
    );
    const onConfirmed = vi.fn();
    render(<MappingReview jobId={JOB} onConfirmed={onConfirmed} />);
    const box = await screen.findByLabelText("I confirm Sale Amount is read correctly");
    expect(box).not.toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Confirm these columns" }));
    expect(await screen.findByText(/Nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText(/needs your confirmation/)).toBeInTheDocument();
    expect(screen.getByText(/required field is missing/)).toBeInTheDocument();
    expect(onConfirmed).not.toHaveBeenCalled();
  });

  it("choosing the GST treatment is sent as an override", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((_u: string, init?: RequestInit) => (init?.method === "POST" ? (sent.push(JSON.parse(String(init.body))), reply({}, 202)) : reply(mapping))));
    render(<MappingReview jobId={JOB} />);
    await screen.findByText("Sale Amount", { selector: "strong" });
    await userEvent.selectOptions(screen.getByLabelText("GST on this amount"), "EXCLUSIVE");
    expect(screen.queryByText(/cannot be used yet/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Confirm these columns" }));
    expect(sent[0]).toEqual({ decisions: {}, overrides: { "1": { tax_inclusion: "EXCLUSIVE" } } });
  });

  it("a field with a validation error blocks confirming and tells the seller what to do", async () => {
    const bad = { ...mapping, fields: [{ ...mapping.fields[0], evidence: { errors: [{ rule: "M-E1", message: "dates are mixed formats" }], warnings: [], confirm_reasons: [] } }] };
    vi.stubGlobal("fetch", vi.fn(() => reply(bad)));
    render(<MappingReview jobId={JOB} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("dates are mixed formats");
    expect(screen.getByRole("button", { name: "Confirm these columns" })).toBeDisabled();
  });

  it("a missing mapping shows a plain error", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply({ detail: "no column mapping for this job" }, 404)));
    render(<MappingReview jobId={JOB} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
