# Metrion — Expense Model Options: dedicated ledger vs extending manual adjustments

**Status:** Options and recommendation for the owner's decision at the start of Phase 3 (prepared 2026-10-21). **No option is implemented.** AC-D11 (expense ingestion) is deferred to Phase 3, not removed from scope.
**Why this exists:** sizing AC-D11 showed that the engine's expense registry cannot safely hold a seller's expense file (`cfo-data-intelligence.md` §6.7a). This compares the two ways forward against the accounting that must stay correct.
**Phase 2a is storage-neutral by design:** the engine formulas take a typed input, `ExpenseLine` (§6), that either option can produce. Nothing in Phase 2a depends on this decision.

---

## 1. What exists today (facts from the code)

- **Expense Tracker** (`backend/services/cfo_actions.py`): `enter_expense` writes a `manual_adjustment` row with `field ∈ {expense.advertising, expense.packaging, expense.storage, expense.logistics, expense.other}`, `target_type ∈ {PERIOD, ACCOUNT, SKU}`, `value = {amount_paise, gst_amount_paise?, marketplace?}`; `expense.other` carries a free-text `reason`. Budgets use `expense.budget`.
- **These pools feed Contribution Profit** (`deterministic-engine.md` §5.6): advertising, packaging, logistics and other become `AdvertisingCosts` / `OtherAllocatedCosts`, allocated by revenue share (§5.10) when account- or period-level. An entry in `expense.other` therefore **reduces contribution profit**.
- **`manual_adjustment`** (`20260917_0001_engine_tables`): `id, tenant_id, target_type, target_ref, field, value jsonb, reason, created_by, created_at, supersedes_id, status`. The field registry exists **only in code** (no database CHECK); `UPDATE` and `DELETE` are revoked from the application role (append-only; "active" = ACTIVE and not superseded); the only index is `(tenant_id, target_type, target_ref, field, status)`. It has **no period column**, so `list_expenses` fetches every active row of a field and **filters by period in Python**. `list_expenses` and the budget code select by the `expense.` **prefix**.
- **Absent advertising entries resolve to ₹0** inside contribution profit (Category E, preserved).

## 2. The accounting that must be correct under either option

| Event | Correct treatment | Where it must show |
|---|---|---|
| **Inventory purchase** (stock bought from a supplier) | Not an expense and not in any profit figure. It is a cash outflow (when paid) and a payable (until paid). Cost reaches profit **only as COGS when units are sold** (`cogs_per_unit × billable_quantity`, engine §5.6). Counting the purchase *and* COGS would double count. | cash movements, payables, inventory commitments |
| **COGS** | Per unit sold at the effective-dated weighted-average cost; `UNAVAILABLE` when a sold SKU has no cost. Never taken from the expense file. | contribution profit |
| **Operating expense** (rent, salaries, software, professional fees, utilities) | Overhead: reduces **operating profit**, not contribution profit. | operating profit, cash movements |
| **Allocated cost** (ads, packaging, logistics pools) | Already inside contribution profit; must **not** be subtracted again in operating profit. | contribution profit |
| **Owner drawings** | Not an expense and not in any profit. A cash outflow in the owner-account block, role-gated. | cash movements (owner account) |
| **Capital item** | Not in profit (depreciation is out of scope). A cash outflow. | cash movements |
| **TCS / TDS** | Tax assets that reduce settlement receipts; never a cost. | cash and tax views |
| **Refund of an expense** (negative amount) | Reduces the expense in its class; sign preserved, never silently absolute-valued. | same class |
| **GST on an expense** | Stored beside the amount; whether it is part of the cost or a creditable input is the seller's confirmed treatment (the fee-GST toggle precedent). Never assumed. | operating profit basis, tax views |

**Cash movements** use the **paid date** of an outflow and the **settlement date** of an inflow; **profit** uses the incurred/expense date. A ledger therefore needs both dates (paid date optional; an unpaid expense is a payable, not a cash movement).

## 3. The options

### Option A — a dedicated expense ledger (engine-owned table `expense_entry`, plus a class-assignment record)

One typed row per transaction: `entry_date`, `paid_date?`, `amount_paise` (signed bigint), `gst_amount_paise?`, `category`, `vendor`, `description`, `payment_ref`, `marketplace?`, `source (FILE | MANUAL)`, provenance (`ingestion_run_id`, `source_row_number`, `identity` digest), `hold` (`POSSIBLE_DUPLICATE | MAY_OVERLAP_UNCONFIRMED | none`), `status`, `supersedes_id`, `created_by/at`. A separate append-only `expense_class_assignment` (`entry` or `category` → `class`, `state SUGGESTED | CONFIRMED`, `suggested_by RULE | MODEL`, `confirmed_by`, `confirmed_at`) keeps **suggestions** apart from **confirmations** (decision OQ2).
- DB-level `CHECK`s on class, state and hold; partial unique index on `(tenant_id, identity)` for duplicate prevention; indexes on `(tenant_id, entry_date, class)` for set-based sums; `UPDATE`/`DELETE` revoked from the application role; RLS identical to every tenant table.
- Existing `expense.*` pools and the Expense Tracker keep working unchanged (legacy pools remain valid inputs to contribution profit).
- **Reverses** the earlier decision that CFO defines no manual-input store (R6/AC17d). The justification is concrete: `manual_adjustment` cannot give the typed, queryable, constrained, classed ledger below (§4).

### Option B — extend `manual_adjustment`

Add a ledger field kind (for example `ledger.expense`, deliberately **not** under the `expense.` prefix) and `expense.class` / confirmation fields, with the transaction details in `value jsonb`.
- Keeps AC17d and the single-store guarantee; smallest schema change.
- Costs: amounts and dates live in jsonb (no typed columns, no CHECK, no date index) so set-based sums need expression indexes or jsonb scans; the registry gives no database-level class or sign constraint; the duplicate identity cannot be enforced by the database; supersession works but a 5,000-row file means 5,000 jsonb rows scanned by every period query (the existing Python-side period filter does not scale to this).
- **Contamination hazard:** `list_expenses`, budgets and pool resolution select by the `expense.` prefix; any new field under it would be listed as, or resolved as, a contribution-profit pool. A different prefix is mandatory, and every prefix consumer must be audited.

### Option C — hybrid (recommended shape): Option A as the source of truth, legacy pools preserved

Ledger rows carry the full transaction record; legacy `expense.*` pool entries continue as seller-entered **pools** for contribution profit. A ledger row classed `ALLOCATED_COST` feeds contribution profit through a resolver that the **cost-ownership matrix** (`cfo-unified-financials.md` §4.3) arbitrates against any legacy pool for the same scope and period (one active owner, otherwise the seller is asked), so nothing is counted twice. No existing pool is migrated or rewritten.

## 4. Comparison

| Criterion | A: ledger | B: extend manual_adjustment | C: hybrid |
|---|---|---|---|
| Class integrity (no contamination of profit) | **DB CHECK + typed class** | code only; `expense.` prefix hazard | **DB CHECK + typed class** |
| Inventory purchase / owner drawing kept out of P&L | enforced by class, tested | enforced by code only | enforced by class, tested |
| Cash movements (paid date vs incurred date) | typed columns | dates in jsonb | typed columns |
| Duplicate prevention (§4.3, AC-D11) | **unique identity index** | cannot be enforced in the DB | **unique identity index** |
| Suggest-only classes (OQ2) | separate suggestion/confirmation records | extra fields, no constraint | separate records |
| Set-based SQL speed (planner executor) | **indexed typed columns** | jsonb scans / expression indexes | **indexed typed columns** |
| Append-only audit | yes (revoke UPDATE/DELETE, supersedes) | yes (existing) | yes |
| Tenant isolation | RLS | RLS | RLS |
| Backward compatibility with the Expense Tracker | unchanged | risk through the shared prefix | unchanged (pools kept) |
| Spec impact | reverses AC17d (justified, needs approval) | none | reverses AC17d for the ledger only |
| Effort and risk | larger now (migration, repo, formulas, ingestion, UI) | smaller now, debt later, contamination risk | as A, plus the ownership resolver |

## 5. Recommendation (the decision is the owner's)

**Option C.** The deciding facts: the ledger needs typed, constrained, indexable columns for correctness and speed; and the existing pools must keep working and keep arbitrating through the ownership matrix. Option B is cheaper today but leaves class integrity to code and puts a profit-contaminating prefix hazard next to every list and budget query. If the owner prefers to keep AC17d unchanged, Option B is workable **only** with a non-`expense.` prefix, an audit of every prefix consumer, and expression indexes, and with the accepted cost of weaker guarantees.

## 6. Storage-neutral contract used by Phase 2a (so nothing waits on this decision)

```
ExpenseLine {
  entry_id: str, category: str, amount_paise: int (signed), entry_date: date, paid_date: date | None,
  confirmed_class: Class | None,        # the seller's confirmation; None until confirmed
  suggested_class: Class | None,        # a hint only; changes no figure
  hold: NONE | POSSIBLE_DUPLICATE | MAY_OVERLAP_UNCONFIRMED,
  marketplace: str | None
}
Class ∈ ALLOCATED_COST | OVERHEAD | OWNER_DRAWING | INVENTORY_PURCHASE | CAPITAL | TAX_ASSET
effective class = confirmed_class, else OTHER_UNCLASSIFIED (suggestions never count)
```
Either option yields these lines; legacy pool entries map to `ALLOCATED_COST` lines already inside contribution profit.

## 7. Acceptance tests required for whichever option is chosen

Golden scenarios, each with exact paise results: an inventory purchase is absent from contribution and operating profit and present in cash outflow and payables; COGS appears only when units sell; owner drawings appear only in the owner-account cash view; rent/salary/software reduce operating profit and not contribution profit; ads/packaging pools are not subtracted twice; a refund (negative) reduces its class; an unconfirmed class leaves the entry unclassified and makes operating profit `PROVISIONAL` with the entry listed; a possible duplicate is held and excluded and listed; a legacy pool plus a ledger row for the same scope and period raises an ownership question and counts once after the seller chooses; tenant isolation; append-only supersession; a 5,000-row file's period query meets the benchmark target.

## 8. Decisions requested

1. Choose A, B or C (recommended: C).
2. Confirm that reversing AC17d is acceptable for the ledger (A/C).
3. Confirm the GST-on-expense treatment is seller-confirmed, stored beside the amount.
4. Confirm cash movements use the paid date and profit uses the incurred date.
