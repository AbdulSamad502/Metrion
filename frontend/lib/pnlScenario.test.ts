import { describe, expect, it } from "vitest";
import { BLANK, buildRequest, emptyForm, newFeeEntry, type PnlForm } from "@/lib/pnlScenario";

const f = (text: string, na = false) => ({ text, na });
const filled = (over: Partial<PnlForm> = {}): PnlForm => ({
  ...emptyForm("amazon"),
  sellingPrice: f("1180"),
  gstRate: f("18"),
  productCost: f("354"),
  packaging: f("23.60"),
  monthlyOrders: f("100"),
  rto: f("0"),
  returns: f("0"),
  adSpend: f("", true),
  fees: { referral: { ...newFeeEntry(), ...f("10") }, closing: { ...newFeeEntry(), ...f("20") }, shipping: { ...newFeeEntry(), ...f("50") } },
  ...over,
});
const ok = (form: PnlForm) => {
  const r = buildRequest(form);
  if (!r.ok) throw new Error(JSON.stringify(r.errors));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the request is an untyped JSON body; the assertions below read nested fields of it
  return r.body as Record<string, any>;
};

describe("form -> request", () => {
  it("sends the reference fixture A1 as exact integer strings", () => {
    const b = ok(filled());
    expect(b.selling_price).toEqual({ state: "set", value: "118000" });
    expect(b.gst_rate_bps).toEqual({ state: "set", value: "1800" });
    expect(b.packaging_cost).toEqual({ state: "set", value: "2360" });
    expect(b.fees.referral.amount).toEqual({ state: "set", value: { kind: "single", amount: "1000" } });
    expect(b.fees.closing.amount.value.amount).toBe("2000");
    expect(b.ad_spend).toEqual({ state: "na" });
    expect(b.targets).toEqual([{ kind: "breakeven" }]);
  });

  it("never turns a blank into zero: a blank field is sent as 'empty'", () => {
    const b = ok(emptyForm("flipkart"));
    for (const k of ["selling_price", "gst_rate_bps", "product_cost", "packaging_cost", "monthly_orders", "rto_bps", "return_bps", "ad_spend", "operating_expenses", "salvage_bps"]) {
      expect(b[k], k).toEqual({ state: "empty" });
    }
    expect(b.fees).toEqual({});
  });

  it("distinguishes 'not applicable' (confirmed zero) from a typed 0 and from blank", () => {
    const b = ok(filled({ productCost: f("0"), packaging: f("", true), adSpend: BLANK }));
    expect(b.product_cost).toEqual({ state: "set", value: "0" });
    expect(b.packaging_cost).toEqual({ state: "na" });
    expect(b.ad_spend).toEqual({ state: "empty" });
  });

  it("blocks the request on an unreadable number instead of dropping it or sending zero", () => {
    const r = buildRequest(filled({ sellingPrice: f("12.345"), productCost: f("abc") }));
    expect(r.ok).toBe(false);
    if (!r.ok) expect(Object.keys(r.errors).sort()).toEqual(["productCost", "sellingPrice"]);
  });

  it("sends money as an integer string, never a JS number", () => {
    const b = ok(filled({ sellingPrice: f("99,999,999,999.99") }));
    expect(b.selling_price).toEqual({ state: "set", value: "9999999999999" });
    expect(typeof b.selling_price.value).toBe("string");
    expect(buildRequest(filled({ sellingPrice: f("100000000000") })).ok).toBe(false);
  });

  it("only sends fees that exist for the marketplace and mode (no stray ids, no quick-mode extras)", () => {
    const quick = ok(filled({ mode: "quick", fees: { referral: { ...newFeeEntry(), ...f("10") }, reverse: { ...newFeeEntry(), ...f("30") } } }));
    expect(Object.keys(quick.fees)).toEqual(["referral"]);
    expect(quick.packaging_cost).toEqual({ state: "empty" });
    const fba = ok(filled({ fulfilment: "fba", fees: { shipping: { ...newFeeEntry(), ...f("50") }, fba_fulfilment: { ...newFeeEntry(), ...f("40") } } }));
    expect(Object.keys(fba.fees)).toEqual(["fba_fulfilment"]);
  });

  it("sends no GST rates for an unregistered seller, and never a tenant", () => {
    const b = ok(filled({ gstStatus: "unregistered" }));
    expect(b.gst_rate_bps).toEqual({ state: "empty" });
    expect(b.purchase_gst_rate_bps).toEqual({ state: "empty" });
    expect(JSON.stringify(b)).not.toMatch(/tenant/i);
  });

  it("rejects a 100% target margin and carries a valid one as an integer string", () => {
    expect(buildRequest(filled({ targetMargin: f("100") })).ok).toBe(false);
    expect(ok(filled({ targetMargin: f("20"), wantBreakeven: false })).targets).toEqual([{ kind: "margin", bps: "2000", basis: "contribution" }]);
  });

  it("makes no fee assumption: the default form carries no fee value at all", () => {
    expect(JSON.stringify(emptyForm("meesho"))).not.toMatch(/"text":"[^"]/);
  });
});
