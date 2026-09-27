"""component_code -> component_kind — data-foundation.md §1.4's registry table, verbatim.
Shared by every adapter so `component_kind` is never guessed per-adapter.

**Additions this pass (flipkart.payments.v1, data-foundation.md §5.1.3).** §5.1.3's
secondary-sourced fee-line research ("commission (marketplace fee), fixed fee, collection fee,
shipping fee, return-shipping fee, 'Non-Order Charges' (advertising / storage), Seller
Protection Fund (SPF) credit for warehouse losses, and subvention / rebate entries") names four
concepts already covered by existing codes (`COMMISSION`, `FIXED_FEE`, `COLLECTION_FEE`,
`SHIPPING_CHARGE` — reused, not duplicated) and four with no fitting existing code, added below:

- `NON_ORDER_FEE` (FEE) — §5.1.3's literally-quoted `"Non-Order Charges"` (advertising /
  storage costs deducted from the seller, not tied to a specific order). Named `_FEE` per this
  registry's kind-not-source-word convention (compare `SHIPPING_CHARGE`, kind `CHARGE`, whose
  real Flipkart header is literally "Shipping Fee" — the code suffix reflects `component_kind`,
  never the source column's own word), since this is a cost deducted from the seller, matching
  every other `FEE`-kind code's semantics, not a charge levied on the customer.
- `RETURN_SHIPPING_FEE` (FEE) — §5.1.3's "return-shipping fee" concept. No literal header string
  for this is quoted anywhere in §5.1.3 (unlike `"Non-Order Charges"`, which is), so
  `flipkart.payments.v1` records this code here as a real, named registry gap without binding
  any column to it — binding a guessed header string would violate this project's "never guess"
  rule (data-foundation.md §2.2 rule 3 / this session's adapter-build instructions).
- `SPF_CREDIT` (CHARGE) — §5.1.3's "Seller Protection Fund (SPF) credit for warehouse losses."
  Kind `CHARGE`, not `FEE`, because this is money credited *to* the seller (a reimbursement),
  the same polarity `SHIPPING_CHARGE`/`GIFT_WRAP_CHARGE` already have, not a deduction. No
  literal header string is quoted in §5.1.3 either — same registry-gap-without-binding treatment
  as `RETURN_SHIPPING_FEE` above.
- `SUBVENTION_REBATE` (CHARGE) — §5.1.3's "subvention / rebate entries," another credit-to-seller
  concept, same `CHARGE`-kind and same no-literal-header-string reasoning as `SPF_CREDIT`.

Every one of the four new codes above is `is_verified=False` wherever it appears (or, for the
three that no column currently binds, simply absent from any `column_map` — a registry entry is
not itself a claim that a column has been found)."""

from __future__ import annotations

COMPONENT_KIND_BY_CODE: dict[str, str] = {
    "COMMISSION": "FEE",
    "MARKETPLACE_FEE_GENERIC": "FEE",
    "PLATFORM_FEE": "FEE",
    "FIXED_FEE": "FEE",
    "COLLECTION_FEE": "FEE",
    "PACKAGING_FEE": "FEE",
    "LOGISTICS_FEE": "FEE",
    "COD_FEE": "FEE",
    "NON_ORDER_FEE": "FEE",
    "RETURN_SHIPPING_FEE": "FEE",
    "SHIPPING_CHARGE": "CHARGE",
    "GIFT_WRAP_CHARGE": "CHARGE",
    "SPF_CREDIT": "CHARGE",
    "SUBVENTION_REBATE": "CHARGE",
    "SELLER_DISCOUNT": "DISCOUNT",
    "PLATFORM_DISCOUNT": "DISCOUNT",
    "CASHBACK_DISCOUNT": "DISCOUNT",
    "SHIPPING_DISCOUNT": "DISCOUNT",
    "CGST": "TAX",
    "SGST": "TAX",
    "IGST": "TAX",
    "UTGST": "TAX",
    "CESS": "TAX",
    "TCS": "LEVY",
    "TDS": "LEVY",
}
