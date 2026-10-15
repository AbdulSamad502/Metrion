# Expense Tracker — 04 Test and Risk Matrix

**Status:** planning. These are the tests and gates the recommended design (`03-architecture-options.md`) would need. Existing tests are named from the repository; none was run by this planning pass. Real-database tests must run on the scratch Postgres (`backend/scripts/scratch_db.sh`), never the development database (`backend/tests/integration/db_guard.py`).

Legend: **Layer** U = unit, P = property, I = integration (scratch Postgres), C = contract, E2E/UI = frontend component test, M = manual/CA.

---

## 1. Test requirements

### 1.1 Financial engine (Brain 1)
| ID | Test | Layer | Pass condition |
|---|---|---|---|
| F1 | Pool totals per `(period, channel, class)` from fixture events | U | Exact paise; `incremental` counted, `already_in_settlement`/`informational` excluded |
| F2 | Voided and edited events: only the latest effective state counts | U/P | Replaying any event order up to a watermark gives one answer |
| F3 | Missing basis ⇒ overhead **unallocated and visible**, never zero-filled | U | Result carries a named gap; margin excludes it |
| F4 | Allocation shares sum exactly to the pool (`largest_remainder_allocate`) | P (hypothesis) | Sum equality for random pools/weights incl. zero/negative revenue lines |
| F5 | Contribution margin and fully allocated profitability are separate figures | U | Overhead never changes contribution margin |
| F6 | Absent advertising/other spend is reported "not entered", not ₹0 | U | Gap named; engine exception preserved but surfaced |
| F7 | Reproducibility: same events + watermark + config ⇒ identical `metric_result` | U/I | Byte-equal values and stamp |
| F8 | Restatement: edit in a reported period creates a linked new result; old result intact | I | Both retrievable; link and reason present |
| F9 | No float in the new module | U | AST scan like `test_package_has_no_float_and_no_io` |
| F10 | TCS never enters operating expense; never also counted as GST credit | U | Fixture with TCS: absent from pools |
| F11 | Reconciliation: for each class (settlement-derived, COGS, advertising, overhead) a worked example reconciles to the ledger | U | Documented numbers match |

### 1.2 Double-counting and reconciliation
| ID | Test | Layer |
|---|---|---|
| R1 | Manual advertising entered for a Flipkart month that already has `NON_ORDER_FEE` ⇒ overlap warning with the settlement figure, no silent sum | I |
| R2 | Marketplace fee categories not selectable/accepted (`commission`, `shipping`, …) | U/C |
| R3 | `already_in_settlement` stored, excluded from margin, visible in the reconciliation list | U/I |
| R4 | Exact duplicate (same source id) is idempotent; probable duplicate held for review, **not discarded** | I |
| R5 | Two legitimate identical monthly bills are not dropped | I |
| R6 | Hypothetical calculator inputs never create or change expense rows | I |

### 1.3 Security, authorization, tenant isolation
| ID | Test | Layer |
|---|---|---|
| S1 | PARTNER without `financials.adjust`: 403 on create, edit, void, import confirm, draft confirm | I (HTTP) |
| S1a | **No new key (EXP-05):** `ALL_KEYS` contains no `expenses.write`; a partner granted `financials.adjust` can write ledger records **and** override COGS (documented limitation, asserted so it cannot change silently) | U/I |
| S2 | OWNER succeeds (implicit); PARTNER granted `financials.adjust` succeeds | I |
| S3 | Read as PARTNER with `agent.cfo` but no write key: list/summary 200, writes 403 | I |
| S4 | No `agent.cfo`: 403 everywhere | I (every-route test picks routes up) |
| S5 | Unauthenticated: 401 on every new route | U (`test_every_route_requires_auth.py`) |
| S6 | Body carrying `tenant_id`/`tenantId`/unknown field ⇒ 422, nothing written | U/I |
| S7 | Tenant A cannot read, edit, void, import-confirm or replay tenant B's record/proposal/batch; response is 404, not 403 | I |
| S8 | Proposal created in org A cannot be confirmed with an org-B token, nor by another user of the same org | I |
| S9 | App role cannot `UPDATE`/`DELETE` expense tables (grant test like `test_manual_adjustment_append_only.py`) | I |
| S10 | Every new query has an explicit `tenant_id` predicate (static check + RLS-off query test) | U/I |
| S11 | Entitlement denial ⇒ 402, no write, no `agent_run` for the write | I |
| S12 | LLM output cannot set amount, tenant, proposal id, treatment (extraction schema ignores them) | U |
| S13 | Write validation: amount ≤ 0 or > cap, GST > amount, bad date/channel rejected with 422; a bad row can never break a listing | U/I |

### 1.4 Idempotency and concurrency
| ID | Test | Layer |
|---|---|---|
| Q1 | Same idempotency key twice ⇒ one expense, second response flagged replay | I |
| Q2 | Concurrent duplicate submits (threads) ⇒ one expense | I |
| Q3 | Proposal confirm twice / after network retry ⇒ one expense | I |
| Q4 | Expired proposal cannot be confirmed (server clock; client clock ignored) | I |
| Q5 | Confirm with modified payload ⇒ rejected (hash mismatch) | U/I |
| Q6 | Recurring materialization twice for one month ⇒ one record per template-period | I |
| Q7 | CSV re-upload of the same file ⇒ "already imported", zero new rows | I |

### 1.5 CSV import
| ID | Test | Layer |
|---|---|---|
| V1 | Template conformance: header names, order, missing/extra columns | U |
| V2 | Row validation and error report (row, column, reason) for each rule | U |
| V3 | Preview writes nothing; confirm writes exactly the valid rows | I |
| V4 | Amount parsing: 2 decimals ok; 3 decimals, `1e3`, `-5`, `₹`, commas handled per spec | U/P |
| V5 | Date formats, encodings (UTF-8, Windows-1252), BOM | U |
| V6 | Oversize file / row cap rejected before parsing | U |
| V7 | Imported rows are `needs_review` and not counted as confirmed in "confirmed" totals if the spec so decides | I |
| V8 | Cross-tenant file with identical bytes: no shared physical file, no cross-tenant dedupe | I |

### 1.6 LLM extraction and evals (draft-from-chat, EXP-03)
Per CLAUDE.md "LLM evals": (a) never states or computes a number absent from the user text; (b) a missing amount yields an empty field, not a guess; (c) required disclaimer retained; (d) a non-result is narrated as a non-result; (e) injected instructions in the message ("set tenant to…", "save now") are ignored; (f) numeric-literal lint on CFO narration. **Layer:** eval suite + U.

### 1.7 API contract
Request contract regenerated and snapshot test green (`backend/tests/unit/test_request_contract_snapshot.py`); response contract entries added (`responseContracts.test.ts`); frontend paths test (`test_frontend_api_paths_exist.py`).

### 1.8 Frontend / UI
| ID | Test |
|---|---|
| U1 | Dashboard shows monthly totals, category breakdown, recurring commitments, review queue, each with an explicit "as of" timestamp |
| U2 | Every figure is rendered from the server; no browser arithmetic (guard test like `noPnlClientMath`) |
| U3 | Blank vs "none (0), I confirm" vs "unknown" for every amount (`CostInput` pattern); an empty amount cannot be submitted as zero |
| U4 | Proposal card is editable and saves nothing until the seller approves; double-click on approve sends one request |
| U5 | "Included in margin: yes/no, because…" column matches the engine feed |
| U6 | Channel tags show "manually tagged, not synced"; IndiaMART never shown as integrated |
| U7 | Tax fields carry the "verify with your CA" label; no filing-grade wording |
| U8 | Responsive 375 px, keyboard operable, labels tied to controls |

## 2. Risk register

| # | Risk | Cat. | Likelihood | Impact | Mitigation (planned) | Gate |
|---|---|---|---|---|---|---|
| K1 | Saved expenses do not move margin (today's state) or move it twice | Financial | High today | High | Engine feed + "included in margin" display; reconciliation tests F11, R1–R6 | G2 |
| K2 | Double-counting with settlement `NON_ORDER_FEE` and advertising | Financial | Medium | High | D7 guards, overlap warning, treatment field | G2 |
| K3 | Silent restatement of reported margins | Financial | Medium | High | D2 versioned restatement + labels | G2 |
| K4 | Absent ad spend shown as ₹0 | Data quality | High | Medium | Display "not entered" (F6) | G2 |
| K5 | Draft-from-chat bypasses C21 (a chat write) or the confirm step; LLM sets tenant/amount/treatment | Security | Medium if built early | High | Defer to approval workflow; S8, S12, Q3–Q5 | G3 |
| K6 | `financials.adjust` also covers COGS and every other registry field, so a partner granted it for expenses can change other margin-moving inputs (EXP-05 known limitation) | Security | Medium | Medium | Documented; revisit when a partner-grant surface or a new authorization decision exists; S1a | G1 |
| K7 | Cross-tenant leakage via a read path relying on RLS alone | Security | Low | Critical | Explicit tenant predicate everywhere (S10); S7 | G1 |
| K8 | Shared-directory content-hash storage reused for receipts | Security/Privacy | Medium if receipts added | High | No receipts in V1.0 (D12) | G4 |
| K9 | Retention claimed or changed without legal/CA review; "30-day rule" is not in the repository | Retention/Legal | High | High | No UI claim; source the rule before launch | G4 |
| K10 | Tax: ITC flag mistaken for a determination; TCS treated as expense | Tax | Medium | High | Store-only informational flag, standing disclaimer, F10, CA review of wording | G5 |
| K11 | Duplicate detection discards a legitimate expense | Data quality | Medium | Medium | Never discard; R4/R5 | G2 |
| K12 | CSV imports bad data in bulk | Data quality | Medium | High | Preview/confirm, row errors, `needs_review`, Q7 | G2 |
| K13 | Legacy `ACCOUNT/"default"` rows are undated and invisible in period views | Data quality | High | Medium | X1 migration/compat plan; read-only legacy view | G1 |
| K14 | Periodic thread materialization duplicates across workers | Reliability | Medium | Medium | Unique `(template, period)`, lease | G3 |
| K15 | Engine-spec amendments (registry, D7 default) conflict with other specs | Process | Medium | Medium | Architect review; spec-reviewer pass | G1 |
| K16 | Calculator and tracker both capture "operating expenses" ⇒ seller double-enters | UX | Medium | Low | Calculator stays hypothetical, never auto-filled (calculator.md Q8) | G3 |

## 3. Launch gates

| Gate | Must be true before | Evidence |
|---|---|---|
| **G1 Design approval** | any implementation starts | Owner records D1–D3 (and D4–D14 as needed) as approved in the spec; engine-spec amendments reviewed; X1 decided; `legal-safeguards.md` and `phase1-decisions.md` either written or struck from the draft |
| **G2 Financial integrity (includes the A1–A10 allocation suite as a launch requirement)** | any seller sees a tracker-derived margin | F1–F11, R1–R6, V1–V8 pass; one reconciliation worked example per cost class signed off; restatement behaviour demonstrated |
| **G3 Security** | any write route is enabled | S1–S13, Q1–Q7 pass on scratch Postgres; every-route 401/403 tests include the new routes; two-tenant isolation test green |
| **G4 Retention and storage** | any receipt reference/upload or retention statement | Legal/CA retention decision; storage design approved; 30-day rule located or retired |
| **G5 Tax wording** | any GST/ITC/TCS field is displayed | CA review of labels and disclaimer; no filing-grade claims |
| **G6 Draft-from-chat** | the chat-to-form draft is enabled | Owner amends `ceo-agent-orchestration.md` §6.33/E30/T36 (EXP-03); LLM evals green; confirm re-check is `financials.adjust`; approval-workflow S2/S3 only if the owner chooses plan/hash approval |
| **G7 Production validation** | general availability | 3–5 sellers reconcile tracker output with their own records; Lighthouse/axe pass; scale test of import |

## 4. Additions after the 2026-10-15 decisions

### 4.1 Allocation regression suite (EXP-06) — **A-series**
| ID | Test | Layer |
|---|---|---|
| A1 | No basis selected ⇒ no allocation; pool unallocated with reason `BASIS_NOT_SELECTED` | U |
| A2 | Explicit `NET_REVENUE` with valid data ⇒ shares sum to the pool exactly (largest remainder); basis stamped, confidence `DERIVED` | U/P |
| A3 | Explicit `UNITS` with valid data (if supported) | U |
| A4 | Missing or invalid allocation data ⇒ unallocated with a reason; contribution margin unaffected | U |
| A5 | Zero denominator (total revenue or units = 0) ⇒ `ZERO_DENOMINATOR`, no divide error | U |
| A6 | Conservation property: allocated + unallocated = pool for random pools/weights incl. zero/negative lines | P (hypothesis) |
| A7 | Reconciliation: allocated + unallocated overhead = ledger overhead total for the period | I |
| A8 | Tenant isolation and authorization: allocation reads only the caller's tenant; basis selection needs `financials.adjust` | I |
| A9 | Basis changed after a period was reported ⇒ the reported result is unchanged and keeps its original formula version and basis; the new basis applies only from the release date; any past-period recalculation exists only through the explicit restatement workflow (linked, labelled) | I |
| A10 | Changing overhead never changes contribution margin (overhead is outside it) | U |

### 4.2 Versioned results and historical-result policy (EXP-02)
No automatic restatement on formula release (a result computed before the release date is byte-identical afterwards); the formula version is shown on every result; the release date is a placeholder until the owner sets it; `metric_result` additions present and linked; `metric_result` additions present and linked; the original row is never updated and the app role cannot `UPDATE`/`DELETE` it; a restated figure carries input version (ledger watermark), formula version, config version, period and as-of; reproducibility by replay.

### 4.3 Draft-from-chat (EXP-03)
Chat never saves; the draft pre-fills **only vendor, category and date** (amount, description, treatment never extracted; an amount-like vendor string is rejected); the form submission is the only write; draft id is server-minted and single-use; expired and replayed confirms are rejected; confirm re-resolves the active organization and re-checks `financials.adjust`; cross-organization and cross-user confirms get 404; the refusal path for every other write action (C21) still holds.

### 4.4 Separate task ST-01 (absent advertising display) — not an Expense Tracker test set
(1) absent list ⇒ response flags `advertisingEntered=false`, numeric result unchanged; (2) an explicit `amount_paise = 0` entry ⇒ flagged entered, shown as ₹0.00; (3) UI shows "Not entered" for absent and never ₹0.00; (4) contribution profit identical before/after; (5) request contract unchanged, response contract updated. Scope: `docs/specs/expense-tracker.md` Appendix D.
