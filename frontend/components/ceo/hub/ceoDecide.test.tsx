import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

// Spec 6.33: the decision forms. Prices and costs are entered here, never typed into chat; every cost is answered explicitly; the run sends integer paise.
const user = () => userEvent.setup();
let fake: FakeCeo;
let feed: ManualFeed;

beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

function mount() {
  return render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
}

async function openInvestigation(id: string) {
  await user().click(await screen.findByTestId("open-drawer")); // the list of conversations lives in the drawer
  await user().click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

async function openForm(testid: string) {
  const id = fake.seed({ id: "inv-1" });
  mount();
  await openInvestigation(id);
  await user().click(screen.getByTestId(testid));
  return screen.findByTestId("decide-panel");
}

describe("decision forms", () => {
  it("a price-impact run sends integer paise, explicit cost states and the chosen competitor, and nothing is assumed", async () => {
    fake.priceForm = {
      competitors: [{ id: "c-1", label: "Acme Steel" }], feeOptions: [{ marketplace: "AMAZON", category: "Home", feeType: "referral" }],
      storedCost: { amountPaise: 30000, formatted: "₹300.00", effectiveFrom: "2026-01-01", reason: null }, maxCandidatePrices: 2,
    };
    const panel = await openForm("open-price-impact");
    const u = user();
    await u.selectOptions(await within(panel).findByLabelText("Competitor"), "c-1");
    await u.type(within(panel).getByLabelText("SKU"), "SKU-1");
    await u.selectOptions(within(panel).getByLabelText("Fee reference"), "AMAZON|Home|referral");
    await u.type(within(panel).getByLabelText("Current price"), "499");
    await u.type(within(panel).getByLabelText("Candidate price 1"), "449.50");
    await u.click(within(panel).getByRole("button", { name: "+ Add a price" }));
    await u.type(within(panel).getByLabelText("Candidate price 2"), "479");
    expect(within(panel).queryByRole("button", { name: "+ Add a price" })).not.toBeInTheDocument(); // the configured limit
    await u.click(within(panel).getByRole("button", { name: "Run price impact" }));
    expect(await within(panel).findByText(/Answer every cost/)).toBeInTheDocument(); // refused in plain words until every cost is answered
    expect(fake.count("postTurn")).toBe(0);
    const choices: [string, string][] = [
      ["Shipping per unit", "None (0), I confirm"], ["Advertising per unit", "Unknown"], ["Return and RTO losses per unit", "An amount"], ["Other costs per unit", "None (0), I confirm"],
    ];
    for (const [label, mode] of choices) await u.click(within(screen.getByTestId(`cost-${label}`)).getByLabelText(mode));
    await u.type(within(panel).getByLabelText("Return and RTO losses per unit amount in rupees"), "12");
    await u.click(within(panel).getByRole("button", { name: "Run price impact" }));
    await screen.findByTestId("processing");
    const args = fake.calls.find((c) => c.method === "postTurn")!.args as unknown[];
    expect(args[3]).toEqual({
      kind: "PLAYBOOK", key: "COMPETITOR_PRICE_IMPACT",
      inputs: {
        competitor_url_id: "c-1", sku: "SKU-1", marketplace: "AMAZON", category: "Home", fee_type: "referral", basis: "INCLUSIVE", gst_rate_pct: null, current_price_paise: 49900,
        candidate_prices_paise: [44950, 47900], shipping: { state: "NONE_CONFIRMED" }, advertising: { state: "UNKNOWN", reason: null },
        return_rto: { state: "AMOUNT", amount_paise: 1200 }, other: { state: "NONE_CONFIRMED" },
      },
    });
    fake.completeTurn({ answer: "ok" });
  });

  it("shows the saved cost with its date", async () => {
    fake.priceForm = { competitors: [], feeOptions: [], storedCost: { amountPaise: 30000, formatted: "₹300.00", effectiveFrom: "2026-01-01", reason: null }, maxCandidatePrices: 3 };
    const panel = await openForm("open-price-impact");
    expect(await within(panel).findByTestId("stored-cost")).toHaveTextContent("₹300.00, effective 2026-01-01");
  });

  it("says plainly when no cost is saved", async () => {
    fake.priceForm = { competitors: [], feeOptions: [], storedCost: null, maxCandidatePrices: 3 };
    const panel = await openForm("open-price-impact");
    expect(await within(panel).findByTestId("stored-cost")).toHaveTextContent("margins will be shown as unavailable");
  });

  it("without a configured price limit the form cannot run, and says why", async () => {
    fake.priceForm = { competitors: [], feeOptions: [], storedCost: null, maxCandidatePrices: null };
    const panel = await openForm("open-price-impact");
    expect(await within(panel).findByText(/has not been configured/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Run price impact" })).toBeDisabled();
  });

  it("saving a cost goes through the CFO expense path as exact paise", async () => {
    fake.priceForm = { competitors: [], feeOptions: [], storedCost: null, maxCandidatePrices: 3 };
    const panel = await openForm("open-price-impact");
    const u = user();
    await u.type(await within(panel).findByLabelText("SKU"), "SKU-1");
    await u.type(within(panel).getByLabelText("New cost per unit"), "1.15");
    await u.click(within(panel).getByRole("button", { name: "Save cost" }));
    await waitFor(() => expect(fake.saved).toHaveLength(1));
    expect(fake.saved[0]).toMatchObject({ target_type: "SKU", target_ref: "SKU-1", field: "cogs_per_unit", value: { amount_paise: 115 } });
  });

  it("new product: a single saved quote is superseded, duties are saved, and the run sends only its own fields", async () => {
    fake.productForm = {
      quotes: [{ id: "q-1", createdAt: "2026-09-01T00:00:00Z", value: { supplier_name: "Acme", unit_cost_paise: 10000 }, reason: null, summary: "Acme: ₹100.00 per unit" }], budget: [], budgetTargetRef: "tenant-a",
    };
    const panel = await openForm("open-new-product");
    const u = user();
    expect(await within(panel).findByTestId("stored-quotes")).toHaveTextContent("Acme: ₹100.00 per unit");
    await u.type(within(panel).getByLabelText("SKU"), "SKU-1");
    await u.type(within(panel).getByLabelText("Supplier name"), "Beta");
    await u.type(within(panel).getByLabelText("Unit cost"), "95");
    await u.type(within(panel).getByLabelText("Duties"), "50");
    await u.click(within(panel).getByRole("button", { name: "Save quote" }));
    await waitFor(() => expect(fake.saved).toHaveLength(1));
    expect(fake.saved[0]).toEqual({ target_type: "SKU", target_ref: "SKU-1", field: "supplier.quote", value: { supplier_name: "Beta", unit_cost_paise: 9500, duties_paise: 5000 }, supersedes_id: "q-1" });
    await u.type(within(panel).getByLabelText("Budget"), "20000");
    await u.click(within(panel).getByRole("button", { name: "Save budget" }));
    await waitFor(() => expect(fake.saved).toHaveLength(2));
    expect(fake.saved[1]).toMatchObject({ target_type: "ACCOUNT", target_ref: "tenant-a", field: "batch.budget", value: { amount_paise: 2000000 } });
    await u.type(within(panel).getByLabelText("Quantity"), "100");
    await u.type(within(panel).getByLabelText("History from"), "2026-07-01");
    await u.type(within(panel).getByLabelText("History to"), "2026-09-30");
    await u.click(within(panel).getByRole("button", { name: "Run new product decision" }));
    await screen.findByTestId("processing");
    const args = fake.calls.find((c) => c.method === "postTurn")!.args as unknown[];
    expect(args[3]).toEqual({ kind: "PLAYBOOK", key: "NEW_PRODUCT_DECISION", inputs: { sku: "SKU-1", quantity: 100, period_start: "2026-07-01", period_end: "2026-09-30" } });
    fake.completeTurn({ answer: "ok" });
  });

  it("the form card from chat opens the form and sends nothing", async () => {
    fake.priceForm = { competitors: [], feeOptions: [], storedCost: null, maxCandidatePrices: 3 };
    const id = fake.seed({ id: "inv-1" });
    mount();
    await openInvestigation(id);
    const u = user();
    await u.type(screen.getByLabelText("Ask the CEO"), "A competitor cut their price");
    await u.click(screen.getByRole("button", { name: "Send" }));
    fake.completeTurn({
      route: "CLARIFY", status: "CLARIFIED", kind: "CLARIFICATION", answer: "Open the form.", compositionMode: null,
      choices: { version: 1, kind: "FORM", slot: "form", options: [{ key: "open-form", label: "Open the price-impact form", kind: "RECOMMENDED", reason: "Entered in the form", form: "COMPETITOR_PRICE_IMPACT" }] },
    });
    const before = fake.count("postTurn");
    await u.click(await screen.findByTestId("card-option-open-form"));
    expect(await screen.findByTestId("decide-panel")).toBeInTheDocument();
    expect(fake.count("postTurn")).toBe(before);
  });
});
