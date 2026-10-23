# Metrion — CEO ↔ CFO ↔ Expense Tracker (chat reads, chat-prepared writes)

**Status:** Draft, written before the code (CLAUDE.md "spec first"), 2026-10-23.
**Related:** `expense-tracker.md` (EXP-03, §7), `expense-tracker-cfo-integration.md`, `ceo-agent-orchestration.md` (C21, §6.11, §6.33–§6.35), `ceo-approval-workflow.md`, `cfo-query-planner.md`, `auth.md`.
**What this adds:** the seller can ask the CEO about their tracked expenses (a month, a date, a range, by category), and can add, correct, remove and mark-paid expenses by talking to the CEO. The CEO also notices when the seller mentions paying for something and *asks* whether to add it.

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| CE1 | The CEO may **read** the Expense Tracker for any date, month or range, by category, and answer from it. Totals come from the engine (`EXPENSE_*` results with an `engineResultRef`), individual entries from a reference to the tracker record itself. | Owner, 2026-10-23 |
| CE2 | The CEO may **add, correct, void (remove) and mark paid** a tracker expense when the seller asks in chat, through the CFO's own write path. **This reverses EXP-03 ("no chat writes") and amends C21 for exactly these four registry keys.** The reversal is the owner's explicit instruction of 2026-10-23, recorded here rather than assumed. Refunds, SKU assignment, review-state changes and CSV import stay on the Expense Tracker page. | Owner, 2026-10-23 |
| CE3 | **Nothing is saved without the seller's explicit approval of the exact values.** A write is prepared as a stored plan card ("Add expense: ₹5,000.00 · Rent · 1 Oct 2026 …") and runs only when the seller presses **Approve** on that card, bound to the plan id and hash (`ceo-approval-workflow.md`). A typed "yes" is just text. | Reuses the approval workflow |
| CE4 | **A model never reads or writes a value.** The amount, date, category and ids are collected by the guided input session and parsed **by code** (`parse_amount_paise`, a date parser, a closed category list, an id picked from the seller's own entries). The classifier only chooses the action key and passes text slots that go through the same parsers. | Hard rule |
| CE5 | **When the seller merely talks about an expense** ("I paid ₹5,000 for office rent yesterday"), the CEO does not act: it asks "Is this an expense of yours — shall I add it to your Expense Tracker?" with Yes / No. Yes starts the add session with what was said already filled in (and asks for the rest, for example the category); No drops it. Nothing is saved on the mention. | Owner, 2026-10-23 |
| CE6 | Every write needs `financials.adjust` and the CFO entitlement, checked when the plan is made and again when it runs, with the real `AuthContext`. A member without it is told so and nothing is prepared. | EXP-05, C8 |
| CE7 | Removing is a **void with a reason** (append-only), never a hard delete; an edit is a linked correction; both are reversible by reading the history on the tracker page. | Tracker rules |
| CE8 | One expense model per seller for now: the **Expense Tracker** (`expense_event`, …) is the one the CEO reads and writes. The CFO 2.0 ledger (`expense_entry`, …) stays as it is (see `cfo-expense-ledger.md` §14.4 — the choice between the two models is still open). | Owner: "use the expense tracker" |

## 2. Design decisions requiring review

| # | Decision | Recommendation |
|---|---|---|
| D1 | Approval granularity | One plan card per write (a card per expense). The seller can ask "add three expenses" only one at a time in V1. |
| D2 | Passive detection precision | Deterministic first-person payment patterns only (verb + amount, not a question, not hypothetical). A false positive costs one question; a false negative costs nothing (the seller can still say "add this expense"). |
| D3 | Per-entry amounts in an answer | Each listed entry is a `Figure` whose ref points at the tracker record (`AGENT_REPORT_FIELD`, source `expense_event`), Register **MANUAL** ("entered by you"). Totals are engine results. At most 12 figures per answer; the rest are said to be on the Expense Tracker page. |
| D4 | Daily / monthly breakdown | Derived by code from words in the seller's question ("month wise", "monthly", "date wise", "day wise", "daily"); one engine summary per month (at most 12) or per day that has entries (at most 12, newest first). |

## 3. Assumptions

* The seller's role holds `agent.ceo`, `agent.cfo` and (for writes) `financials.adjust`; the CFO is attached to the conversation.
* The Expense Tracker's category list (`expense_ledger_rules.CATEGORIES`) is closed; amounts are integer paise, at most the tracker's ceiling.
* Dates are interpreted in the seller's calendar day (no time zones).

## 4. Goals and non-goals

**Goals.** CE1–CE8; answers that cite stored results; a clear card before any write; plain explanations when something cannot be done.
**Non-goals.** Refunds, SKU split, review-state changes, recurring templates and CSV import from chat; editing several expenses at once; reading a bill or receipt image; any marketplace write; inferring a category with a model; guessing an amount or date.

## 5. Data model

No new tables. Reads use `expense_event` / `expense_status_event` through `expense_tracker_repo` and the engine summary (`ledger_feed` → `EXPENSE_*` metric results). Writes use the tracker's own repository functions through its own route handlers, so validation, idempotency (`idempotency_key = ceo-plan-<plan id>`), the audit `agent_run` row and the read-model version bump are unchanged.

## 6. Core rules

1. `cfo.expense_summary` (READ): slots = question, period; builds `period_start/end/as_of`; optional breakdown by code (D4); returns the engine summary per bucket (every figure carries its `engineResultRef`) and the entries in the window (≤ 12, newest first) with their record ids.
2. `cfo.expense_add`, `cfo.expense_correct`, `cfo.expense_void`, `cfo.expense_paid` (RECORD_ENTRY, `force_approval`): inputs come only from the input session; the plan freezes them; the handler is the tracker's own write path wrapped to accept the frozen slots.
3. The session asks one question at a time, each answer parsed by code; a text that does not parse is asked again with the reason; Back and Cancel work; nothing is saved by answering.
4. To correct, void or mark paid, the seller picks **one of their own entries** (the three that best match what they said, or the latest three); the id is never typed or invented.
5. The answer after a write states, in words written by code, what was saved or why nothing was, with the amount as a `Figure` referencing the saved record.
6. A mention of an expense (CE5) starts the add session only after Yes; the mention text is kept only as pre-filled answers that pass the same parsers.

## 7. AI requirements

* The model may select `cfo.expense_*` and fill the text slots `question`, `period`, `amount`, `product`(unused) — never an id, a date or a number that is used as-is.
* Narration of read answers goes through the existing composer and gate; writes are acknowledged by code-written text.
* LLM evaluation of the classifier's choice between `cfo.expense_*` and the other actions is **deferred** (no real model is called in this cycle); the deterministic rules in `intent_router` decide the common phrases without a model.

## 8. Authorization and security

`agent.ceo` + `agent.cfo` + entitlement for reads; `financials.adjust` additionally for every write (plan creation and execution). Tenant from the session; no tenant id or record id accepted from chat text. Plans are bound to (tenant, investigation, requester, hash, expiry) as for all approvals. A removal needs a reason (asked, 500 characters, free text stored as a note — never interpreted).

## 9. Edge cases

E1 no expenses in the window → "nothing recorded" (never zero) · E2 amount zero or negative or above the ceiling → asked again · E3 date in the future → asked again · E4 category not recognised → options offered, never guessed · E5 two matching entries → the seller picks · E6 the entry is already voided → said, nothing prepared · E7 duplicate approval click → idempotent replay · E8 plan expired → re-ask · E9 member without `financials.adjust` → explained, nothing prepared · E10 the mention is a question or hypothetical → ignored · E11 the same mention repeated → asked again once per message.

## 10. Production-validation blockers

PV1 the passive-detection patterns are tuned on English and Hinglish sentences written by us, not on real chats · PV2 no measured evaluation of the classifier with a real model · PV3 plan-card wording is not final copy · PV4 the choice between the two expense models (CE8) is open.

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC-X1 | "How much did I spend in September?" returns the tracker's total for that month with an `engineResultRef`; an empty month says nothing is recorded, never zero |
| AC-X2 | "Month wise / date wise" gives one engine summary per month / per day that has entries |
| AC-X3 | "List my expenses for 5 October" shows each entry as a figure citing its record |
| AC-X4 | "Add an expense" (any phrasing from the rule list) starts the session; every answer is parsed by code; no model parses a value |
| AC-X5 | After the last answer a plan card shows the exact values; nothing is saved until Approve; a typed yes saves nothing; declining saves nothing |
| AC-X6 | Approve saves exactly the frozen values once (idempotent), writes the audit row, bumps the read-model version; the same question afterwards includes it |
| AC-X7 | Correct / void / mark-paid act on an entry the seller picked from their own list; a void needs a reason and keeps the history |
| AC-X8 | A member without `financials.adjust` is told so; no plan is created |
| AC-X9 | Another tenant's entry id (forged) is refused; chat never accepts a tenant id |
| AC-X10 | A first-person payment statement is answered with a question; No saves nothing; Yes starts the add session with the mention pre-filled |
| AC-X11 | Questions, hypotheticals and statements without an amount never trigger the mention question |
| AC-X12 | Registry/effect guards: exactly the four write keys carry `RECORD_ENTRY`, all `force_approval`; all other keys unchanged |

## 12. Test scenarios

Routing matrix rows (add / correct / remove / list / summary / mention) through the real `run_turn`; session unit tests for each parser (amount, date, category, entry pick); plan-card text; approve-once; permission and cross-tenant cases; evidence tests (figures only through refs; digit-free sentences); registry/effect guard tests updated for `RECORD_ENTRY`.

## 13. Explicit open questions

| # | Question |
|---|---|
| OQ1 | Should the CEO also offer to add an expense it finds in an uploaded file or screenshot? (Not built.) |
| OQ2 | Should several mentioned expenses in one message be offered together? (V1: one at a time.) |
| OQ3 | Choose one expense model (CE8). |

## 14. Implementation status (2026-10-23, re-pointed at the CFO ledger)

**Owner decision (2026-10-23): the CFO ledger is the authoritative expense source.** This spec was written against the Expense Tracker; every chat action now uses the ledger instead (decisions CE1 to CE7 about the conversation, the approval card and the permission are unchanged; CE8 is resolved by this decision). The Expense Tracker's tables are no longer read or written by the chat.

Built and tested: the five actions (summary read; add, correct, remove, mark paid behind the plan-card Approve), the mention question ("Is this an expense of yours?"), day and relative periods, evidence figures through entry references, the permission gate (`financials.adjust`), and tenant isolation including forged ids. What changed with the move:

* **Reads** run the planner's `EXPENSE_BY_CATEGORY` per bucket (month, day or whole range), so every total is a stored engine result with a reference, and entries on hold are named as left out of the totals.
* **Add** writes one ledger entry (category stored as the closed list's plain label). It gets **no confirmed class**: the answer says so, and Operating Profit moves only after the seller confirms a class (suggest-only, OQ2). A repeat of the same expense is stored **on hold** as a possible duplicate and is in no total until reviewed; the answer says so.
* **Correct** replaces the entry with a new one that names it (the original stays in the history) and carries its payment statement.
* **Remove** needs a reason of a few words (3 to 300 characters), kept with who, when and why.
* **Mark paid** supports UNPAID, PARTIALLY_PAID (asks how much; must be above zero and below the whole) and PAID. "Unknown" is no longer an option: no statement reads as "not stated".
* **Bridge:** entries made on the Tracker's own page reach the ledger only when the seller asks (`/cfo/ledger/tracker-bridge`), idempotent, no double counting, no silent migration (`cfo-expense-ledger.md` 14.4).

Proof: `tests/unit/test_ceo_expense_chat.py` (pure parsing and routing), `tests/integration/test_ceo_expense_tracker_chat.py` (26: add, duplicate, decline, cancel, reads incl. month-wise, date-wise and empty, remove with reason, pick, change, paid, unpaid, partly paid, partial refused, mention, permission, forged id), plus the approval-gate, effects, architecture, periods and registry guards.

Still open (not hidden): no real-model wording evaluation (the conversation is rule-driven; no model fills a field); the ledger has no "unknown" payment state by design; the class of a chat-added expense is confirmed on the CFO Expenses tab, not in chat.
