import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

import { BusinessDetailsDialog } from "@/components/profile/BusinessDetailsDialog";
import { BusinessProfileSteps } from "@/components/profile/BusinessProfileSteps";
import { STEPS, formErrors, EMPTY_FORM } from "@/lib/businessProfile";

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const stub = (h: Handler) => {
  const f = vi.fn(async (url: string, init?: RequestInit) => h(url, init));
  vi.stubGlobal("fetch", f);
  return f;
};
afterEach(() => vi.unstubAllGlobals());

const SAVED = {
  businessName: "Asha Home Goods",
  description: "We sell steel kitchen storage to families.",
  categories: "Kitchen storage",
  marketplaces: ["AMAZON", "FLIPKART"],
  priceSegment: "MID_RANGE",
  targetCustomer: "Urban families",
  businessStage: "GROWING",
  state: "Gujarat",
  updatedAt: "2026-10-20T10:00:00+00:00",
};
const isPut = (init?: RequestInit) => init?.method === "PUT";

describe("first-run steps", () => {
  it("asks one question per slide and refuses to move on while the answer is blank", async () => {
    stub(() => json({ profile: null, complete: false, suggestedName: null }));
    render(<BusinessProfileSteps onSaved={vi.fn()} />);
    const user = userEvent.setup();
    expect(screen.getByRole("heading", { name: STEPS[0].title })).toBeInTheDocument();
    expect(screen.getByText("Question 1 of 8")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Business name is required/);
    expect(screen.getByRole("heading", { name: STEPS[0].title })).toBeInTheDocument(); // still on the first slide
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
  });

  it("walks all eight slides, then saves every answer in one PUT without a tenant id", async () => {
    const f = stub((url, init) => (isPut(init) ? json({ complete: true }) : json({ profile: null, complete: false, suggestedName: "Asha Stores" })));
    const onSaved = vi.fn();
    render(<BusinessProfileSteps onSaved={onSaved} />);
    const user = userEvent.setup();

    const name = await screen.findByLabelText(STEPS[0].title);
    await waitFor(() => expect(name).toHaveValue("Asha Stores")); // pre-filled from the workspace name
    await user.clear(name);
    await user.type(name, "Asha Home Goods");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(await screen.findByLabelText(STEPS[1].title), "We sell steel kitchen storage to families.");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(await screen.findByLabelText(STEPS[2].title), "Kitchen storage");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("checkbox", { name: "Amazon" }));
    await user.click(screen.getByRole("checkbox", { name: "Flipkart" }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("radio", { name: /Mid-range/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(await screen.findByLabelText(STEPS[5].title), "Urban families");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("radio", { name: /Growing/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.selectOptions(await screen.findByLabelText(STEPS[7].title), "Gujarat");
    expect(screen.getByText("Question 8 of 8")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const put = f.mock.calls.find(([, i]) => isPut(i))!;
    expect(JSON.parse(String(put[1]!.body))).toEqual({
      business_name: "Asha Home Goods",
      description: "We sell steel kitchen storage to families.",
      categories: "Kitchen storage",
      marketplaces: ["AMAZON", "FLIPKART"],
      price_segment: "MID_RANGE",
      target_customer: "Urban families",
      business_stage: "GROWING",
      state: "Gujarat",
    });
  });

  it("Back returns to the previous slide and keeps the answer", async () => {
    stub(() => json({ profile: null, complete: false, suggestedName: null }));
    render(<BusinessProfileSteps onSaved={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(STEPS[0].title), "Asha");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("button", { name: "Back" }));
    expect(await screen.findByLabelText(STEPS[0].title)).toHaveValue("Asha");
  });
});

describe("Settings → Business details dialog", () => {
  it("opens pre-filled with the saved details", async () => {
    stub(() => json({ profile: SAVED, complete: true, suggestedName: null }));
    render(<BusinessDetailsDialog onClose={vi.fn()} onSaved={vi.fn()} />);
    const dialog = await screen.findByRole("dialog", { name: "Business details" });
    await waitFor(() => expect(within(dialog).getByLabelText(STEPS[0].title)).toHaveValue("Asha Home Goods"));
    expect(within(dialog).getByLabelText(STEPS[7].title)).toHaveValue("Gujarat");
    expect(within(dialog).getByRole("checkbox", { name: "Amazon" })).toHaveAttribute("aria-checked", "true");
    expect(within(dialog).getByRole("checkbox", { name: "Meesho" })).toHaveAttribute("aria-checked", "false");
    expect(within(dialog).getByRole("radio", { name: /Mid-range/ })).toHaveAttribute("aria-checked", "true");
  });

  it("saves an edit with the full set of fields and reports it", async () => {
    const f = stub((url, init) => (isPut(init) ? json({ complete: true }) : json({ profile: SAVED, complete: true, suggestedName: null })));
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<BusinessDetailsDialog onClose={onClose} onSaved={onSaved} />);
    const user = userEvent.setup();
    const name = await screen.findByLabelText(STEPS[0].title);
    await waitFor(() => expect(name).toHaveValue("Asha Home Goods"));
    await user.clear(name);
    await user.type(name, "Asha Retail");
    await user.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
    const body = JSON.parse(String(f.mock.calls.find(([, i]) => isPut(i))![1]!.body));
    expect(body.business_name).toBe("Asha Retail");
    expect(Object.keys(body).sort()).toEqual(["business_name", "business_stage", "categories", "description", "marketplaces", "price_segment", "state", "target_customer"]);
  });

  it("refuses to save when any field is cleared: nothing is sent and the seller is told to fill everything in", async () => {
    const f = stub(() => json({ profile: SAVED, complete: true, suggestedName: null }));
    render(<BusinessDetailsDialog onClose={vi.fn()} onSaved={vi.fn()} />);
    const user = userEvent.setup();
    const desc = await screen.findByLabelText(STEPS[1].title);
    await waitFor(() => expect(desc).toHaveValue(SAVED.description));
    await user.clear(desc);
    await user.click(screen.getByRole("checkbox", { name: "Amazon" }));
    await user.click(screen.getByRole("checkbox", { name: "Flipkart" })); // no marketplace left
    await user.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByText("Please fill in every field before saving.")).toBeInTheDocument();
    expect(screen.getByText(/Description is required/)).toBeInTheDocument();
    expect(screen.getByText(/Choose at least one marketplace/)).toBeInTheDocument();
    expect(f.mock.calls.some(([, i]) => isPut(i))).toBe(false);
  });

  it("shows the server's refusal in plain words and never claims it saved", async () => {
    const onSaved = vi.fn();
    stub((url, init) => (isPut(init) ? json("forbidden", 403) : json({ profile: SAVED, complete: true, suggestedName: null })));
    render(<BusinessDetailsDialog onClose={vi.fn()} onSaved={onSaved} />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByLabelText(STEPS[0].title)).toHaveValue("Asha Home Goods"));
    await user.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
    expect(onSaved).not.toHaveBeenCalled();
  });
});

describe("client checks mirror the server", () => {
  it("an empty form has an error for every one of the eight fields", () => {
    expect(Object.keys(formErrors(EMPTY_FORM)).sort()).toEqual(STEPS.map((s) => s.key).sort());
    expect(STEPS).toHaveLength(8);
  });
});
