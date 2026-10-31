# CMO 3.0 — B7 controlled browser walkthrough (prepared, NOT performed)

Status: **BLOCKED** — not performed. Nothing below has been run in a browser. Automated tests (API, chat, component level, synthetic data) are the only workflow evidence so far and are **not** browser verification.

## Dependency (exact)
* A dedicated **test tenant**: one Clerk organization created for testing, separate from the shared development tenant (standing rule: no records are created in the shared dev tenant), with its own synthetic data only.
* A sign-in the owner performs themselves (no password is shared or typed by the assistant), on a frontend + backend running against a database that holds only test records.
* The owner's permission for one walkthrough, with LLM generation steps either (a) run on the owner's chosen local model, accepting that failures are expected and safe, or (b) limited to the zero-credit steps (1–6, 9–15) and the plan card of step 7 declined.
* Plan with enough test credits, or the billing step marked skipped. No real seller credits are spent.

## Synthetic data
Product "AquaNest 1 L steel bottle" (facts: stainless steel, 1 litre, 12-hour insulated if the owner confirms), marketplace AMAZON; a second product on FLIPKART for the wrong-marketplace checks; a synthetic performance CSV (Date, SKU, Impressions, Clicks, Orders, Units Sold, Sales) covering 28 days around a chosen go-live date, with a few blank cells and one missing day.

## Steps, expected results and what to record
Record for each step: PASS/FAIL, a screenshot reference, and the console/network errors seen. After steps 1, 7, 10, 12, 13 reload the page and confirm the data persists.

| # | Workflow | Where | Expected |
|---|---|---|---|
| 1 | Product creation and fact confirmation | CMO page / CEO hub | facts saved only after the seller confirms; unconfirmed facts shown as not confirmed |
| 2 | PI-to-CMO hand-off | CEO hub | the CMO flow starts from the PI product; no duplicate product |
| 3 | Keyword research | CEO hub | evidence-based list; unsupported demand shown NOT_ASSESSED |
| 4 | Five titles and scores | CEO hub | five titles, score separate from marketplace compliance (NOT_ASSESSED) |
| 5 | Mobile/desktop preview | CEO hub card | switching screen/marketplace needs no new request; card says ILLUSTRATIVE |
| 6 | Buyer questions and readiness | CEO hub | free; saves only seller statements |
| 7 | Listing plan and approval | CEO hub | plan card first; typing "yes" does not approve; approval is a click; same request key never bills twice |
| 8 | Content audit and revision | CEO hub | audit has no "compliant" verdict; a bullet rewrite changes only that bullet |
| 9 | Copy and used states | listing card | approved, copied and used are separate; nothing is published |
| 10 | History and comparison | CEO hub | versions listed per product; compare shows changed fields |
| 11 | Performance import | /dashboard/cmo/performance | preview first; import only on click; the same file again is "already imported"; blank cells stay blank |
| 12 | SKU-to-product confirmation | performance page and chat | chat proposes with a Save button; "yes" saves nothing; replacing an earlier link asks first |
| 13 | Go-live confirmation | performance page and chat | same rules as 12 |
| 14 | Before/after analysis | performance page | equal-length windows; a day without data makes the total "not assessed", never zero; wording observational, never causal |
| 15 | CEO routing and hand-offs | CEO hub | each CMO phrase reaches its card; insight links prefill the chat bar and send nothing |

Cross-checks during the run: a second signed-in user in a different organization sees none of these records; no step publishes anything; every refusal shows a plain message; the units balance changes only where steps 7/8 are approved.

## Afterwards
Record results in `CMO_PRODUCTION_READINESS.md` §5 with date, tester, build commit, tenant id (not credentials) and any defects. Only then may B7 move to PARTIAL/PASS.
