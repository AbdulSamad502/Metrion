---
name: metrion-domain
description: Indian e-commerce marketplace fee structures, GST basics, and marketplace terminology as Metrion defines them. Use when reading or writing anything touching revenue, fees, GST, settlements, or marketplace-specific data shapes (Amazon/Flipkart/Meesho) in this codebase — terms here have precise, spec-defined meanings, not generic e-commerce meanings.
---

# Metrion domain vocabulary

Source of truth for everything below: `docs/specs/deterministic-engine.md` and `docs/specs/cfo-agent.md`. If this skill and a spec ever disagree, the spec wins — update this file, don't trust memory over it.

## Revenue and discounts

- **Gross Order Value** — pre-discount line total, tax-exclusive (§5.2).
- **Discount `bearer`** — every discount component is tagged `SELLER`, `MARKETPLACE`, or `UNKNOWN`. Only `SELLER`-borne discounts reduce Net Realized Revenue; `MARKETPLACE`-borne ones are disclosed only, never subtracted. `UNKNOWN` is conservatively treated as `SELLER` and flagged `DERIVED` (§5.3). Bearer is a *configured* property of `(marketplace, component_code)` — never hardcoded, never inferred.
- **Net Realized Revenue** = Gross Order Value − seller-funded discounts − cancellations − returns − RTO unrecovered revenue (§5.5).

## Costs

- **COGS** — weighted-average cost, effective-dated, billed only on quantity actually sold (returns/RTO with recovered sellable inventory don't consume COGS) (§5.6).
- **MarketplaceFees** — summed from settlement-side data where available, else invoice-side; always tax-exclusive.
- **RTO (Return to Origin)** has three distinct outcomes, each with different revenue/COGS/logistics treatment: inventory recovered-sellable, recovered-damaged, or lost in transit (§5.7). Never collapse these into one bucket.

## Contribution Profit

`ContributionProfit = NetRealizedRevenue − COGS − MarketplaceFees − ShippingLogistics − AdvertisingCosts − ReturnRTOLosses − OtherAllocatedCosts` (§5.8). This is Metrion's core number — always engine-computed, always cites an `engine_result_ref`, never a float.

## GST — management-grade, not filing-grade

Metrion's GST support is explicitly **not** statutory filing software (§1.3). It covers inclusive/exclusive normalization, CGST/SGST/IGST/Cess handling, and an indicative tax summary — every rendering carries a disclaimer that it isn't a GST return.

- **Inclusive vs exclusive basis is declared per source, never inferred.** Meesho reports are GST-*inclusive*; Amazon MTR supplies both bases; Flipkart is per-field (§8.1). Treating everything as exclusive silently overstates Meesho revenue by the GST rate — a real, named failure mode in the spec, not a hypothetical.
- **TCS and TDS are not costs.** They're prepaid tax credited to the seller's account, shown in cash-flow/settlement views only — they never appear in Contribution Profit (§5.9, D6).
- **GST Applicability Lookup** — an on-demand *research* feature, structurally isolated from the calculation engine. It returns a `PROVISIONAL` likely rate with mandatory `source_url`/`retrieved_at`; it never enters a calculation automatically and never applies retroactively to historical periods (§8.4, L1–L7).

## Marketplace terminology

- **MTR** — Amazon's Merchant Transaction Report, the primary settlement-side source.
- **Settlement side vs invoice side** — the same transaction is reported twice, once at time of sale (invoice) and once at time of payout (settlement). Leak Shield's core signal is the *delta between them* per `component_code` — this is where recoverable money is found (`cfo-agent.md` §6.2).
- **Leak Shield** — not a separate agent, a capability inside CFO. Brain 1 emits `reconciliation_exception` rows (the arithmetic); CFO classifies and prioritizes them (the judgment) (`cfo-agent.md` C2, D1).
- **True Margin** — Metrion's branded term for Contribution Profit / Contribution Margin%, computed exclusively by Brain 1. No agent — including CI, which observes competitor prices — holds its own margin formula.
