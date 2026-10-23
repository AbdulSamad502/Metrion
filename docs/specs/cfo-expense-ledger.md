# Metrion — CFO Expense Ledger Specification (Phase 3a)

**Status:** Draft for review (CFO 2.0, Phase 3a). Owner decision 2026-10-21: **Option C** of `cfo-expense-model-options.md` — a dedicated, engine-owned expense ledger as the source of truth, with the legacy `expense.*` pools preserved.
**Prerequisites:** `cfo-expense-model-options.md` (the decision and the accounting that must stay correct) · `cfo-unified-financials.md` §4.2–4.3 (classes, cost-ownership matrix) · `cfo-data-intelligence.md` §6.7/§6.7a (expense ingestion, AC-D11) · `deterministic-engine.md` §5.17.1 (EXPENSE_BY_CATEGORY, OPERATING_PROFIT) · `cfo-query-planner.md` · `auth.md` (tenancy)
**Built on:** Phase 2a formulas `expense_accounting.py` (`ExpenseLine`, `expense_breakdown`, `operating_profit`) — this spec supplies the storage that produces `ExpenseLine`s; no formula changes.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| E1 | **Option C**: a dedicated ledger (`expense_entry`) is the source of truth for seller expenses; legacy `expense.*` pools keep working as seller-entered contribution-profit pools and are never migrated or rewritten. | owner 2026-10-21 |
| E2 | This **reverses AC17d ("CFO defines no manual-input store") for the ledger only**; justified by typed/constrained/indexed columns, DB-enforced duplicate identity and class integrity. | owner 2026-10-21 |
| E3 | **Classification is suggest-only (OQ2).** A suggestion changes no figure; only a seller *confirmation* does. An unconfirmed entry is `OTHER_UNCLASSIFIED`: excluded from both profit figures, listed, and it makes operating profit `PROVISIONAL`. | decision OQ2 |
| E4 | **Profit uses the incurred (entry) date; cash movements use the paid date.** An unpaid expense is a payable, not a cash movement. | options doc §8 (recommended; confirmed by approving C) |
| E5 | **GST on an expense is stored beside the amount; whether it is part of the cost or a creditable input is the seller's confirmed treatment, never assumed.** Until confirmed the amount is used as entered and the entry carries `GST_TREATMENT_UNCONFIRMED`. | options doc §2 |
| E6 | Operating profit = Contribution Profit − Σ confirmed `OVERHEAD`; `ALLOCATED_COST` is already inside CP and is never subtracted again; owner drawings, inventory purchases, capital items and tax assets never reach a profit figure (Phase 2a matrix). | engine §5.17.1 |
| E7 | Missing is not zero: with no ledger entry and no seller declaration for a period, operating profit is `UNAVAILABLE`. | engine §5.17.1 |
| E8 | The ledger is **append-only** (no UPDATE/DELETE for the application role); a correction is a new row that supersedes the old one. | project rule |

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Exact-duplicate vs possible-duplicate | `identity` = SHA-256 of (entry_date, amount, category, vendor, payment_ref, description), **unique per tenant among ACTIVE rows** → an exact repeat is skipped and counted. Same (date, amount, vendor) with a different identity → stored with `hold = POSSIBLE_DUPLICATE`, excluded from every total, listed for the seller. | Repeated legitimate payments (same rent each month) differ in date; a same-day same-amount same-vendor pair with different text is exactly the ambiguous case to ask about. |
| D2 | Overlap with marketplace deductions | A category that maps to a marketplace-owned component (commission, fixed fee, collection fee, TCS/TDS) is stored with `hold = MAY_OVERLAP_UNCONFIRMED` until the seller confirms it is not already deducted in a settlement. | Cost-ownership matrix §4.3: one owner per component. |
| D3 | What "overhead coverage" means | `SOURCE_PRESENT` when the ledger has at least one active, non-held entry dated in the period; `DECLARED_NONE` when the seller declared "no overhead expenses" for a period containing it; otherwise `NONE`. **Completeness of the seller's expense capture cannot be proven by the system** — operating profit carries the number of entries behind it and is never labelled complete beyond that. | No invented threshold (OQ1). |
| D4 | Where a confirmed class is stored | `expense_class_assignment` (separate append-only table): scope `ENTRY` or `CATEGORY`, state `SUGGESTED \| CONFIRMED`. Effective class = latest confirmed ENTRY assignment, else latest confirmed CATEGORY assignment, else unclassified. | Keeps suggestions and confirmations apart (E3) without mutating the ledger. |
| D5 | Legacy pools in the ledger view | Read-only list alongside the ledger (class `ALLOCATED_COST`, source `LEGACY_POOL`); they are not copied into it. A ledger `ALLOCATED_COST` entry for the same scope and period as a legacy pool of the same category is an ownership conflict: **only the established source counts (pool before ledger), the other is excluded, the figure is labelled and one data request is raised** until the seller picks the authoritative one (§4.3; amended 2026-10-22, see §14.2.1). | Nothing double counted, nothing silently dropped. |

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Sellers keep expenses in a spreadsheet with at least date, category and amount (mapped by the existing mapping machinery, `report_kind=EXPENSE`). | Medium: unusual layouts need manual mapping (dashboard track). |
| A2 | Amounts in an expense file are tax-exclusive unless the seller confirms otherwise (GST-inclusive mapped amounts remain refused at mapping time, R3). | Medium |
| A3 | The Expense Tracker's `expense.*` pools stay the way sellers enter contribution-profit pools in V1. | Low |

## 4. Goals and non-goals

**Goals:** a typed, constrained, tenant-isolated, append-only expense ledger; manual entry and file ingestion into it; duplicate and overlap prevention; seller-confirmed classes; `ExpenseLine`s for the engine; `EXPENSE_BY_CATEGORY` and `OPERATING_PROFIT` available to the planner with honest coverage; every ledger write bumps `cfo_read_model_version`.

**Non-goals (this phase):** payables, cash forecast and owner-account view (Phase 3c); depreciation; bank-statement reconciliation; automatic classification (suggestions only); migrating legacy pools; any UI (dashboard track).

## 5. Data model

All tables: `tenant_id uuid not null`, `ENABLE`+`FORCE ROW LEVEL SECURITY` with the standard tenant policy, `GRANT SELECT, INSERT` only to `metrion_app` (no UPDATE/DELETE/TRUNCATE), classified in the tenant data inventory.

```
expense_entry {
  id uuid pk, tenant_id,
  source text CHECK (FILE | MANUAL), ingestion_run_id uuid null, source_row_number int null,
  entry_date date not null, paid_date date null,
  amount_paise bigint not null            -- signed: a refund of an expense is negative
  gst_amount_paise bigint null, gst_treatment text null CHECK (INCLUDED_IN_COST | CREDITABLE),
  category text not null, vendor text null, description text null, payment_ref text null, marketplace text null,
  identity text not null,
  hold text not null default 'NONE' CHECK (NONE | POSSIBLE_DUPLICATE | MAY_OVERLAP_UNCONFIRMED),
  supersedes_id uuid null, is_void boolean not null default false,   -- a correction is a new row naming the row it replaces; a void is a row with is_void
  created_by uuid not null, created_at timestamptz not null
}
  -- ACTIVE = not a void and no later row names it in supersedes_id (computed, because the application role cannot UPDATE)
  unique (tenant_id, identity) WHERE NOT is_void AND hold = 'NONE'   -- uniqueness among entries that can count toward totals; the write path also skips a repeat of a held entry
  index (tenant_id, entry_date), index (tenant_id, supersedes_id)
expense_class_assignment {
  id, tenant_id, scope text CHECK (ENTRY | CATEGORY), entry_id uuid null, category text null,
  class text CHECK (the seven classes), state text CHECK (SUGGESTED | CONFIRMED),
  suggested_by text null CHECK (RULE | MODEL), reason text null,
  confirmed_by uuid null, confirmed_at timestamptz null, created_at, supersedes_id uuid null
}   -- CHECK ((scope='ENTRY') = (entry_id IS NOT NULL)); CHECK ((state='CONFIRMED') = (confirmed_by IS NOT NULL))
expense_period_declaration {
  id, tenant_id, period_start date, period_end date, declaration text CHECK (NO_OVERHEAD),
  declared_by uuid, declared_at, supersedes_id uuid null
}
```

## 6. Core rules

1. **Write path** (manual or file): normalise → compute `identity` → exact repeat skipped and counted → same (date, amount, vendor) with another identity stored as `POSSIBLE_DUPLICATE` → marketplace-deduction-like category stored as `MAY_OVERLAP_UNCONFIRMED` → insert → bump `cfo_read_model_version` **in the same transaction**.
2. **Effective class** per D4. A confirmation re-validates that the class is one of the seven and that confirming `ALLOCATED_COST` for an entry whose scope/period is covered by a legacy pool of the same category raises the §4.3 ownership question instead of silently double counting.
3. **Ledger → engine:** `ExpenseLine(entry_id, category, amount_paise, entry_date, paid_date, confirmed_class, suggested_class, hold, marketplace)`; held and superseded rows are handled exactly as Phase 2a already specifies (held → excluded, listed). Period filtering is by `entry_date`.
4. **OPERATING_PROFIT** = Phase 2a `operating_profit(contribution_profit, lines, coverage)`; `EXPENSE_BY_CATEGORY` = `expense_breakdown(lines, period)`. Both return `UNAVAILABLE` per E7; both state how many entries, how many unclassified and how many held stand behind them.
5. **Legacy pools** keep feeding Contribution Profit exactly as today; the ledger never changes a CP figure except through rule D5 (a conflict excludes both and asks).
6. **Permissions:** writes need `financials.adjust` (AC11) and record `created_by`; reads need `agent.cfo`.
7. **No LLM in the path.** A model may *suggest* a class (state `SUGGESTED`, `suggested_by MODEL`) from a category/description via the local provider; no figure changes until a seller confirms. Narrated figures carry `FigureToken`s as elsewhere.

## 7. AI requirements

Suggestions only (E3), from masked fields (category text, never amounts or vendors' payment references), local Ollama behind `LlmProvider`, off unless configured. Required evals before any seller sees suggested classes: never states a number, never confirms a class, never drops the "suggestion" label. **Deferred by decision**; the rule-based suggester ships first (category keyword table, state `SUGGESTED`, `suggested_by RULE`).

## 8. Authorization and security

Tenant RLS on every table; no endpoint accepts `tenant_id`; no UPDATE/DELETE grant; `financials.adjust` for writes; the owner-drawing view is role-gated in Phase 3c. A cross-tenant leak test is part of acceptance.

## 9. Edge cases

E1 refund (negative) reduces its class, sign preserved · E2 expense dated outside every uploaded sales period still counts for its own period · E3 a category with no assignment is unclassified (listed, PROVISIONAL) · E4 an entry whose class is later confirmed changes figures only from the confirmation's write (read-model version bumps) · E5 a confirmed class superseded by a later confirmation uses the later · E6 identical rows within one file collapse to one with the repeat counted · E7 same row in a re-uploaded file is skipped (counted) · E8 GST treatment unconfirmed → flagged, amount as entered · E9 declaring NO_OVERHEAD for a period that already has OVERHEAD entries is refused (the declaration must be superseded after the entries are held/removed) — matching Phase 2a · E10 an entry with no category is rejected at write time, not defaulted · E11 re-adding content identical to an entry that was later voided is refused as a duplicate of the voided original; the seller restores it by superseding the void instead (a deliberate consequence of append-only identity).

## 10. Production-validation blockers

PV-E1 CA review of OPERATING_PROFIT treatment, GST-on-expense treatment and the owner-drawing view · PV-E2 real seller expense files (layouts, category vocabularies) to tune the keyword suggester · PV-E3 category→class defaults are *not* seeded (the seller confirms); a CA-reviewed starter table may be offered later · PV-E4 5,000-row period-query timing on realistic hardware.

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC-L1 | A ledger row cannot be updated or deleted by the application role; a correction or a void is a new row. |
| AC-L2 | Class, hold, status and GST-treatment values are enforced by database CHECKs; amounts are signed bigint. |
| AC-L3 | An exact duplicate is skipped and counted; a same-day same-amount same-vendor different-text row is held and excluded; a marketplace-deduction-like category is held until confirmed. |
| AC-L4 | Only a confirmed class affects any figure; a suggestion changes nothing. |
| AC-L5 | Golden scenarios (options doc §7), each to the paisa: inventory purchase absent from both profits; COGS only on units sold; owner drawing only in the owner view; rent/salary/software reduce operating profit only; ads/packaging not subtracted twice; a refund reduces its class; unconfirmed → unclassified + PROVISIONAL + listed; held excluded + listed. |
| AC-L6 | `OPERATING_PROFIT` is `UNAVAILABLE` with no entries and no declaration; `DECLARED_NONE` yields a value; a declaration contradicting existing OVERHEAD entries is refused. |
| AC-L7 | Every ledger write bumps `cfo_read_model_version` in the same transaction (a planner cache entry is invalid afterwards). |
| AC-L8 | A ledger `ALLOCATED_COST` entry and a legacy pool for the same scope/period → exactly one counts (the established pool), labelled + one data request; the seller's choice decides which counts, never both. |
| AC-L9 | Tenant isolation holds for all three tables and the planner metrics. |
| AC-L10 | An expense file ingests through the mapping machinery into the ledger with duplicate/overlap handling and a data-quality report; the four-file 80k acceptance scenario runs end to end. |
| AC-L11 | The planner answers `EXPENSE_BY_CATEGORY` and `OPERATING_PROFIT` from the ledger with the oracle-style equality to the per-line formulas. |

## 12. Test scenarios

TL1 refund · TL2 inventory purchase · TL3 owner drawing · TL4 rent vs ad pool · TL5 duplicate in file / across files · TL6 possible duplicate · TL7 overlap-like category · TL8 suggestion-only · TL9 confirmation then supersession · TL10 declaration contradictions · TL11 legacy-pool conflict · TL12 cross-tenant · TL13 read-model bump · TL14 append-only grants · TL15 period boundaries on entry_date vs paid_date · TL16 planner equality.

## 13. Explicit open questions

| # | Question |
|---|---|
| OQ-L1 | Is "at least one non-held entry in the period" an acceptable definition of `SOURCE_PRESENT` (D3), or must the seller declare "expenses complete" per period before operating profit is shown at all? (Recommendation: keep D3 and print the entry count; add a "complete" declaration later if sellers need it.) |
| OQ-L2 | Which categories count as marketplace-deduction-like for D2 (initial list: commission, fixed fee, collection fee, closing fee, shipping fee, TCS, TDS)? |
| OQ-L3 | Should the rule-based suggester ship with a starter category table, or stay empty until PV-E2? (Recommendation: a small, clearly labelled starter table of unambiguous words — rent, salary, software — all `SUGGESTED`.) |
| OQ-L4 | GST treatment default for an expense file whose GST column is mapped but treatment unconfirmed: amount-as-entered with a flag (as specified), or block until confirmed? |

---

## 14. Implementation status — Phase 3a (2026-10-21)

### 14.1 Built and verified

| Area | Where | Verified by |
|---|---|---|
| Three append-only tables with database CHECKs, RLS, partial unique identity index; application role limited to SELECT and INSERT | `calc-engine` migration `20261021_0014` | `test_expense_ledger_repo.py` (privileges, CHECKs, identity uniqueness); least-privilege and tenant-inventory guards updated |
| Pure rules: normalisation, identity, duplicate and overlap holds | `calc_engine/expense_ledger.py` | `test_expense_ledger_rules.py` (22 tests) |
| Repository: add (batch, atomic), correct, void, release hold, suggest/confirm class, declare "no overhead", period lines, overhead coverage; every write bumps `cfo_read_model_version` in the same transaction | `calc_engine/repositories/expense_ledger_repo.py` | `test_expense_ledger_repo.py` (17 tests): golden scenarios of the options doc §7 to the paisa (rent vs allocated pool, inventory purchase, owner drawing, capital, tax asset, refund), suggestion-only classes, holds, supersession, version bump and rollback, tenant isolation, period edges |
| Service policy + HTTP: `POST/GET /cfo/ledger/entries`, `…/correct`, `…/void`, `…/release`, `POST /cfo/ledger/classes`, `POST /cfo/ledger/declarations/no-overhead`; `financials.adjust` for writes, `cfo.expense_ledger` entitlement, unknown fields refused | `backend/services/cfo_expense_ledger.py`, `api/v1/cfo.py` | `test_cfo_expense_ledger.py` (routes, gates, 400 messages, tenant isolation) |
| Rule-based class SUGGESTIONS (small starter table, state SUGGESTED, never a figure) | `cfo_expense_ledger.suggest_for_category` | route and ingestion tests |
| Expense file ingestion (mapping → confirmation → ledger, one transaction, quarantine threshold, quality report) | `data_foundation/ingestion/expense_stream.py`, `job_runner.py`, `adapters/mapped.py`, `mapping/vocab.py` (`expense_paid_date`, `expense_gst_amount`; `expense_amount` may mix signs: refunds), `POST /cfo/uploads` with `report_kind=EXPENSE`, `marketplace=ALL` | `test_expense_ingestion.py` (7 tests); four-file benchmark |
| Planner: `EXPENSE_BY_CATEGORY` and `OPERATING_PROFIT` from the ledger and Brain 1, with refs, PROVISIONAL status, unclassified/held exposure, entry count, data requests; operating profit withheld when the book is partial across marketplaces | `cfo/planner/executor.py`, `backend/services/cfo_planner_backend.py` | `test_planner_ledger_metrics.py` (7), `test_cfo_expense_ledger.py` (planner part, real database) |

AC-L1 ✔ · AC-L2 ✔ · AC-L3 ✔ · AC-L4 ✔ · AC-L5 ✔ · AC-L6 ✔ · AC-L7 ✔ · **AC-L8 ✔ as amended in 14.2.1** (the conflict rule changed from "exclude both" to "established source keeps counting, labelled") · AC-L9 ✔ · AC-L10 ✔ (synthetic; mocked mapping) · AC-L11 ✔ for the planner's ledger metrics (their values are Brain 1's own functions applied to ledger lines; there is no separate fast path to compare against).

### 14.2 Narrower than the spec — open, not hidden

1. **Ledger `ALLOCATED_COST` — built (Phase 3 finalization, 2026-10-22), with one deliberate change to D5.** A ledger entry confirmed as `ALLOCATED_COST` must name its cost pool (`allocated_component`: advertising, packaging, storage, logistics, other; migration 20261022_0017 enforces it) and then reaches Contribution Profit. For a component, marketplace and period exactly one source counts — the Expense Tracker pool (`POOL`), the ledger (`LEDGER`) or, for advertising, an uploaded report (`REPORT`). The seller picks the owner with `POST /cfo/costs/owner` (append-only `cost_owner_choice`, a later choice supersedes). **Change from D5 as first written:** D5 said an unresolved conflict excludes *both*. That would make a Contribution Profit figure drop a cost the seller has been seeing for months the moment a ledger entry is added. Instead the *established* source keeps counting (`POOL` > `REPORT` > `LEDGER`), the other is excluded, the figure carries a `COST_SOURCE_CONFLICT_<component>_<marketplace>` label (advertising: `ADVERTISING_SOURCE_CONFLICT_<marketplace>`), advertising metrics for that marketplace read UNAVAILABLE with a data request, and the proactive scan raises one signal. Nothing is ever counted twice; nothing is silently dropped. Tests: `test_cfo_costs_resolve.py` (truth table + property), `test_cfo_cost_arbitration.py` (exact paise, choice flips the result, tenant isolation, route gates). Not built: arbitration by SKU or sub-month periods (ledger spans are calendar months).
2. **"Source present" is a floor, not completeness (D3, OQ-L1).** One non-held entry in a period makes operating profit available (PROVISIONAL while anything is unclassified or held); the system cannot know the seller entered everything. The answer states how many entries stand behind it.
3. **OQ-L1–L4 are APPROVED at the recommended defaults (owner, 2026-10-22):** OQ-L1 keep D3 and print the entry count; OQ-L2/L3/L4 as follows — the deduction-like word list is `commission, fixed fee, collection fee, closing fee, shipping fee, tcs, tds`; the suggester ships a small starter table; GST in a file is stored with treatment unconfirmed and the amount used as entered. **GST treatment stays unconfirmed until verified:** `gst_treatment` is NULL on every entry, is not accepted by the HTTP entry model (a request carrying it is refused 422), and no figure treats a GST amount as input credit.
4. **Cash movements, payables and the owner-account view are Phase 3c.** The ledger stores `paid_date`, but nothing reads it yet.
5. **Voiding then re-adding identical content is refused** as a duplicate of the voided original (E11); a correction is the supported path.
6. **No UI.** The review/confirm/release flows exist as API only (dashboard track).
7. **Seller-facing GST, CA and category-default questions (PV-E1…E3) remain open.**



### 14.4 Two expense models coexist after the 2026-10-23 merge (needs an owner decision)

A teammate's Expense Tracker (`feat/expense-tracker-pnl-calculator`, merged into this branch) built a separate, event-sourced expense ledger: `expense_event`, `expense_status_event`, `expense_template`, `expense_assignment`, routes under `/cfo/expense-ledger/*`, a P&L feed behind `EXPENSE_LEDGER_FEEDS_PNL` (default off), CSV import/export, recurring/amortized templates and SKU splits, and the page `/dashboard/cfo/expenses`. This spec's ledger (`expense_entry`, `expense_class_assignment`, `expense_period_declaration`; routes `/cfo/ledger/*`; planner metrics `OPERATING_PROFIT` and `EXPENSE_BY_CATEGORY`; the CFO tab **Expenses**) is a different set of tables.

* **Nothing collides:** table names, routes and migration chains are distinct (the migration lines are joined by `20261023_0017`; this branch's `20261022_0015` was renamed `20261022_0015c` because both lines had used that id).
* **They do not see each other:** an expense entered in one is not in the other, so Operating Profit (this spec) and the teammate's P&L feed can disagree, and the same cost entered in both would be counted in each. Until one model is chosen, enter business expenses in one place only.
* **Decision needed:** keep one. Recommended: keep this spec's ledger as the source for the planner/Operating Profit (it carries holds, suggest-only classes, cost-ownership arbitration and the per-marketplace coverage rules) and migrate the teammate's templates, amortization and SKU splits onto it, or the reverse after review. Not done here because it changes the data model of both.
* **Where the CEO stands (2026-10-23):** the CEO's expense conversation (add, show monthly or date-wise, change, remove, mark paid) reads and writes the teammate's Expense Tracker only, and says so in its answers. It never touches this ledger, so the choice above is still open and no seller figure was changed by the chat feature.

**Decision (owner, 2026-10-23): the CFO ledger is the authoritative expense source** for Operating Profit and the planner. The Expense Tracker stays usable and compatible through one explicit mapping layer (`backend/services/expense_bridge.py`), with no duplicate counting and no silent migration:

* `GET /cfo/ledger/tracker-bridge` previews what would be brought over (count, entries, and the entries not bridged with the reason); it adds nothing.
* `POST /cfo/ledger/tracker-bridge` (ledger write permission) brings the entries over, only when the seller asks. Each carries `payment_ref = tracker:<expense id>`, so a second run adds nothing, and an entry voided in the ledger is not added back. The ledger's own duplicate and overlap holds still apply.
* Not bridged: removed or draft Tracker entries, entries marked "already in settlement" or "informational", and zero amounts. Amounts pass through unchanged; category becomes the Tracker's plain label so the ledger's class suggestions can read it; class confirmation stays the seller's.
* Tests: `tests/integration/test_expense_bridge.py` (preview adds nothing; sync once, second sync adds nothing; voided stays out; non-costs skipped; cross-tenant isolation).

**Done (2026-10-23, same day):** the CEO's expense conversation now reads and writes the CFO ledger (see 14.5 and `ceo-expense-tracker-chat.md` section 14). An expense added in chat is in the ledger at once, with no confirmed class; the bridge is only for entries made on the Tracker's own page.

### 14.5 Payment states and an auditable removal reason (2026-10-23)

Migration `20261023_0018`; `calc_engine/expense_ledger.py` (`validate_payment`, `validate_void_reason`); `expense_ledger_repo` (`set_payment`, `payments_for`, `get_entry`, `find_active_by_identity`, `void_entry(..., reason)`).

* **Payment state** is a statement the seller makes about one entry: `UNPAID`, `PARTIALLY_PAID` (with the amount paid so far, above zero and below the whole) or `PAID`. It lives in the append-only `expense_payment_event` table (SELECT and INSERT only for the application role, FORCE RLS); the latest event per entry is its state; **no event reads as "not stated"**, never as unpaid or paid. A repeat of the current state writes nothing. A removed or replaced entry takes no payment statement. A correction carries the statement to the new entry unless the new amount makes a partial payment impossible (then it is not carried, not guessed). Payment state is information about cash: it does not move any profit figure, so it does not bump the read-model version and does not touch cached planner answers. Routes: `POST /cfo/ledger/entries/{id}/payment`; `GET /cfo/ledger/entries` returns `paymentStatus`, `paidAmountPaise`, `paidAmountDisplay`.
* **Removal reason**: removing an entry now requires a reason of 3 to 300 characters. It is stored on the void row (`expense_entry.void_reason`) together with who removed it and when (`created_by`, `created_at`) and which entry it removed (`supersedes_id`); the original row is never changed. The database refuses any new void row without a reason (a `NOT VALID` check, so removals recorded before this change stay readable). `POST /cfo/ledger/entries/{id}/void` takes `{"reason": "..."}`; a request without one is a 422.
* **Tracker bridge** carries the Tracker's payment status (`unpaid`, `partially_paid`, `paid`) onto the bridged entry; the Tracker's `unknown` stays "not stated".
* **Tests:** `calc-engine` unit `test_expense_ledger_rules.py` (payment shapes, reason bounds) and integration `test_expense_ledger_repo.py` (append-only history, latest wins, DB constraints, reason kept with who/when, correction carry-over); backend `test_cfo_expense_ledger.py` (routes), `test_expense_bridge.py`, `test_ceo_expense_tracker_chat.py` (the chat path end to end).
