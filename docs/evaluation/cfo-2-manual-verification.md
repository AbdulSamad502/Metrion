# CFO 2.0 — manual verification guide

For the owner's hands-on check after CP-E. Everything here was exercised by automated tests first; this is the walk-through to see it with your own eyes.
Wording, GST treatment and tax-adjacent labels still need a CA review (skipped for now by decision).

## 1. Start the app

```bash
docker compose up -d                      # Postgres (pgvector) + Redis
cd backend && uvicorn backend.main:app --reload
cd frontend && npm run dev                # http://localhost:3000, sign in with Clerk
```

Optional switches (copy from `backend/.env.example`; both are OFF unless set, and every flow below works without them):

| Setting | Turns on |
|---|---|
| `CFO_MAPPING_MODEL=qwen3:8b` (Ollama running) | automatic column proposals for unfamiliar files. Without it you map the columns yourself (section 3). |
| `CFO_PLANNER_MODEL=qwen3:8b` | open financial questions in CEO chat (for example "which SKU made the most profit in September?"). Without it the CEO says open questions are not switched on. |
| `CFO_RISK_SCAN_ON_CHANGE=true` | the proactive check runs after each upload instead of only on "Check my data now". |

## 2. Your real Meesho GST workbooks (`gst_3609938_1_2026.zip`)

CFO → **Data & imports** → What is this file? **Sales / orders**, Marketplace **Meesho** → upload `tcs_sales.xlsx`, then `tcs_sales_return.xlsx` (unzip first).
Expected: both are recognised by themselves (no mapping step). `tcs_sales.xlsx` reads 9 rows, `tcs_sales_return.xlsx` reads 6; both "Finished" with nothing held.

## 3. The three mock MTR reports (`Documents/Ecom_Analysis/Data/Raw`)

Upload each as **Sales / orders** for its marketplace. Each ends "Could not be read" with **Map the columns yourself**; click it and choose, for the columns below (everything else stays *Not used*). Then **Use these columns**, tick *I confirm* on each field that asks, and **Confirm these columns**. Each file should finish with 40 rows read, 40 saved, nothing held.

Dates: Amazon is month/day/year (**date mdy**); Flipkart and Meesho are day-first (**date dmy**). Money columns: read as **rupees to paise**, GST **excludes GST**.

| Column (by position) | Amazon | Flipkart | Meesho |
|---|---|---|---|
| order reference | 5 Order ID | 5 Order ID | 1 Order Number |
| line reference | 9 Shipment Item ID | 9 Line Item ID | 2 Sub-Order Number |
| SKU | 13 SKU | 13 SKU | 3 Item Name |
| quantity | 10 Quantity | 10 Quantity | 4 Quantity |
| gross item amount | 38 Item Price | 38 Product Price | 6 Item Price |
| taxable amount | 52 Total Item Taxable Value | 52 Total Item Taxable Value | 14 Total Taxable Value |
| invoice date | 2 Invoice Date (mdy) | 2 Invoice Date (dmy) | 0 Order Date (dmy, e.g. 15-Sep-25) |
| order date | 8 Order Date (mdy) | 8 Order Date (dmy) | — |
| return status | 78 Return Status | 77 Return Status | 42 Return Status |
| component amount: *Platform fee* | 50 Platform Fee | — | — |
| component amount: *Marketplace fee (generic)* | 75 Marketplace Fee Amount | — | — |
| component amount: *Commission* | — | 50 Commission Fee | 12 Commission Fee |
| component amount: *Fixed fee* | — | 48 Fixed Fee | 11 Fixed Fee |
| component amount: *Collection fee* | — | 46 Collection Fee | 10 Collection Fee |
| component amount: *Packaging fee* | — | 44 Packaging Fee | — |
| component amount: *Logistics fee* | — | — | 13 Logistics Fee |

Then check **Profitability → By marketplace**. Gross Sales per marketplace should equal the sum of that file's *Item Price* / *Product Price* column (the automated test checks this to the paisa).
Contribution Profit stays **Not available** until you give a cost per unit for each SKU (CFO → Tools → the cost tools) — that is correct: a missing cost is never treated as zero.

## 4. Things worth trying

1. **Overview**: six figures each with its badge; click *Why this figure?* for source, formula version, exclusions and missing inputs. GST / tax assets reads "GST treatment is not confirmed yet". Financial health shows a band or says why it cannot.
2. **Expenses**: upload an expense file (kind *Business expenses*) or use the Expense Tracker. Suggested classes are not counted until you confirm them; an *allocated cost* needs you to pick which cost (packaging, advertising …). A cost recorded in two places for the same dates is counted once and labelled; pick the right one with the owner choice.
3. **Leak Shield**: findings by claim-window urgency. Amazon is "Provisional — withheld". *Draft claim text* gives order identifiers only. Status buttons record what *you* did; Metrion files nothing.
4. **Cash & Tax**: expected settlements are an estimate from your own history, "not your bank balance". Add a payable in rupees (for example `12500.50`). *Download workbook* gives the CA pack.
5. **Held rows**: upload a file where one order line appears twice with different values; the second is held, not counted, and listed under the upload with *Keep the earlier data* / *Discard this row*.
6. **CEO Hub** (planner model on): ask "which SKU made the most profit in September?" — the answer's figures link to stored results; anything unavailable is said in words.

## 5. Known limits (not defects)

* Replacing earlier data with a held row, and keeping both rows with a reference, are not available yet (they need a decision on how superseded rows are stored).
* Settlement-lag and cash-shortfall status are on the dashboard only, not narrated in chat.
* No measured evaluation of a real model's mapping proposals, plans or routing was run (no real model is called in tests).
* Responsive layout and keyboard use are covered by unit tests, not yet looked at in a browser by a person.
* Amazon and Flipkart findings stay provisional/withheld until join keys are validated on real exports.
* The old standalone Expense Tracker (`/dashboard/cfo/expenses`, built by a teammate, event-sourced) and the CFO 2.0 expense ledger are two separate expense models that coexist; see `docs/specs/cfo-expense-ledger.md` §14.
