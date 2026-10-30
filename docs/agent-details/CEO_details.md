# CEO — Agent and Hub Details

> Describes the CEO as **built in the repository on 2026-10-21** (branch `feat/ci-upgrade`). A readable companion to the specs, not a replacement:
> authority is `docs/specs/ceo-agent-orchestration.md`, `ceo-approval-workflow.md`, `ceo-cmo-delegation.md`, `ceo-pi-research-flow.md`, `agent-memory.md`, `agent-needs-and-shared-knowledge.md` and `agent-flow-visualization.md`. Where this file and a spec disagree, the spec wins.
> Status documents (`docs/planning/ceo-build-status.md`, last updated about 2026-10-10) and some spec status lines are **older than the code** — see §1.14.

**One line:** the CEO is the seller's **single conversational interface** and the operating layer above CFO, CI, PI and CMO. It understands the question, routes work to specialists through a **fixed registry**, asks the seller for what's missing, gets approval before anything costs quota or leaves Metrion, structures what comes back, and advises on questions no specialist owns. **It never computes money and never lets an LLM decide what code runs.**

| | |
|---|---|
| Phase 1 | The agent — how it works and what it does |
| Phase 2 | The dashboard — the CEO Hub: what is shown and how |

---

# PHASE 1 — The agent: how it works and what it does

## 1.1 What the CEO is (and is not)

| The CEO **is** | The CEO is **not** |
|---|---|
| The one place the seller talks to, for every agent | A calculator — no money figure is ever originated, summed, rounded or estimated by it |
| A router over a **closed action registry** and a few fixed **playbooks** | An open tool-using agent — no LLM → tool → LLM loop, no LangGraph/LangChain orchestrator |
| A reader of **persisted verified results** ("Business State") | A re-computer — reads never trigger fresh computation |
| A collector of missing inputs, one question at a time | A guesser — a missing marketplace, period or cost is asked, never defaulted |
| A gatekeeper: stored plan + click-to-approve before metered or data-leaving work | A writer — no marketplace write, no edit of the seller's books, no write-class action in the registry |
| An honest advisor (qualitative, labelled) | A source of benchmarks, GST rates, fees or forecasts from model knowledge |

**One agent, not a swarm.** Situation awareness, priority, decision support, memory, briefings and follow-ups are deterministic services and state machines inside `agent.ceo`. The CEO LLM has exactly **two seams**: **classification** (pick a route from a closed enum) and **composition** (write prose around placeholders), plus a bounded rolling-summary call. Nothing else.

## 1.2 The hard boundaries (enforced in code, not prompts)

1. **Typed evidence only.** The composer gets `Figure`/`Finding` objects whose values are pre-formatted strings with mandatory references. The LLM interface (`complete(model, prompt) -> str`) has no numeric parameter.
2. **Placeholder rendering.** The model writes `{{F3}}`; code substitutes the stored, formatted value. A numeral the model types itself (digits, currency, percentages, spelled amounts, lakh/crore, Devanagari/full-width digits…) **fails the gate** and the answer falls back to a fixed template.
3. **Provenance gate.** Every figure's reference is resolved against the owning table **for this tenant** before it can reach the seller; unresolvable or cross-tenant → dropped and the gap named. `engine_result_ref` and `estimate_ref` are never interchangeable.
4. **One dispatch choke point.** Every specialist call runs `permission → attachment → entitlement → validated slots → call` with the real authenticated context, and writes a child `agent_run`. The registry is the only import of specialist handlers (architecture tests fail the build otherwise; there is no SQL inside the CEO package).
5. **No write-class action** in the registry (`cfo.enter_expense`, file ingest, competitor CRUD, rate overrides etc. are excluded) so the CEO can never be a privilege-escalation layer.
6. **Untrusted text is data.** Competitor titles, review themes, search results, GST page text, attachment text and image text reach the composer only as delimited, labelled evidence; instructions inside have no authority and the classifier never sees them.
7. **Approval is a click, not a sentence** (§1.7).

## 1.3 The turn pipeline

```
message ─► admission (permission, turn cap, lock) ─► ONE classification ─► code validates the plan
   ─► per-leg preflight (permission, attachment, entitlement; all-or-nothing for metered legs)
   ─► Business State reads / registry action / playbook legs (parallel, each a child agent_run)
   ─► evidence table ─► composition (≤1 call, or none for pure reads) ─► numeral + provenance gate
   ─► persisted message, turn, findings (+ display snapshot) ─► Hub shows findings as each leg lands
```

**Routes** (closed enum): `BUSINESS_STATE` (answer from saved results), `ACTION` (one registry key), `PLAYBOOK` (one playbook's parallel legs), `ADVISORY`, `SYNTHESIZE` (wrap up findings already found, no new legs), `CLARIFY`, `OUT_OF_SCOPE` ("publish this listing" is declined).

**How the route is chosen:** a **deterministic intent router** (rules for known phrasings, e.g. product ideas, add-ons like "description with the GST %") runs first; the **LLM classifier** handles the rest. Any value outside the catalog it was shown becomes `CLARIFY`, never executed. The catalog shown is already narrowed to *attached ∩ member-permitted ∩ entitled* agents, but the choke point re-checks everything regardless.

**UI-initiated turns skip the classifier entirely** (quick-action chips, canvas actions, form-run buttons): they send an explicit registry key or playbook id plus declared slots, still through the same choke point. This is the main latency lever — first finding in ~0.2–0.4 s versus ~13–27 s for a typed question on the owner's laptop (single runs from the build record, not benchmarks).

**Other turn mechanics:** per-investigation turn serialisation (`TURN_IN_PROGRESS`), idempotent resend via a client request id, a hard per-leg deadline and stuck-turn recovery (outcomes can be `INTERRUPTED` / `TIMED_OUT_REPEATABLE` / `TIMED_OUT_UNCERTAIN`; an uncertain external effect is never auto-retried or described as "did not happen"), live stage events over SSE with a polling fallback, a Business State cache keyed by `(tenant, entry, data_version)` (authorization checked before any cache read), and a rolling summary of older messages that holds no figures.

## 1.4 The action registry and playbooks

**Registry (closed catalog; each also needs `agent.ceo` + the agent's own key):**

| Agent | Examples of registered keys |
|---|---|
| CFO | `cfo.pnl_for_tenant`, `cfo.pricing`, `cfo.landed_cost`, `cfo.batch_size`, `cfo.supplier_ranking`, `cfo.reconcile`, `cfo.anomaly_check`, `cfo.financial_health`, `cfo.cash_reconciliation`, `cfo.strategic_briefing` (always dispatched without its own narration), `cfo.gst_lookup` (Route A) |
| Shared | `service.gst_lookup` (Route B) |
| PI | `pi.discover` (also needs `research.niche_run` and a READY brief), `pi.supplier_lookup`, `pi.report`, `pi.shortlist_top5` |
| CI | `ci.discover_competitors`, `ci.request_price_scenario`, plus the evidence/competitor/monitor actions listed in `CI_details.md` |
| CMO | the title, listing-copy, description, bullets, keywords, backend-terms, hashtags, catalog, niche, approval and trend actions listed in `CMO_details.md` |

Each entry records slots (typed, no free text, never a tenant id), extra permissions, the entitlement resolver, an **effect** (`READ`, `COMPUTE_PERSIST`, `GENERATE_METERED`, `RECORD_CHOICE`; `WRITE` is not permitted), and fixed parameters.

**Playbooks (only way a turn runs more than one action):** legs are parallel, independent, and fixed in code; the LLM only picks the id.

| Playbook | Answers | Legs |
|---|---|---|
| `PROFIT_DIAGNOSIS` | "Why did my profit drop?" | `cfo.financial_health`, `cfo.anomaly_check`, `cfo.strategic_briefing` + state reads |
| `CASH_AND_LEAK_CHECK` | "Am I being paid what I'm owed?" | `cfo.cash_reconciliation`, `cfo.reconcile` |
| `BUSINESS_BRIEFING` | "Give me my business briefing" | none — persisted reads only; fast and cheap |
| `COMPETITOR_PRICE_IMPACT` | "A competitor cut their price — what does it do to me?" | `ci.request_price_scenario`, `cfo.pricing` (CI facts + CFO margin; the Layer 2 fusion) |
| `NEW_PRODUCT_DECISION` | "Should I stock this, and how much?" | `cfo.landed_cost`, `cfo.batch_size`, `cfo.supplier_ranking` |

The two decision playbooks read **stored seller inputs** (cost per unit, supplier quotes with optional duties, batch budget) and take typed per-run slots. Every cost field is explicitly an amount, "none (0), I confirm", or "unknown" — a silent zero is never accepted, and an unknown cost makes every dependent figure `UNAVAILABLE` with a named data request.

## 1.5 Business State (how the CEO "knows the business")

A fixed catalog of read functions over persisted, verified results — never fresh computation. Each entry carries `status` (`AVAILABLE`, `STALE`, `PARTIAL`, `UNAVAILABLE`, `NOT_ENTITLED`, `NOT_PERMITTED`, `NOT_ATTACHED`), an `as_of` date, figures with a register (`VERIFIED`, `DERIVED`, `MANUAL`, `ESTIMATE`, `UNAVAILABLE`), and named gaps. Built entries include latest P&L, recent P&L, open leaks, data gaps, health bands, seller context/facts, ingestion status, competitor snapshot, PI report latest, CMO workflow/content, shared findings. CFO-class entries need `agent.cfo` **and** CFO entitlement (otherwise the gated preview or a wall). Agent-owned entries are readable only while that agent is attached to the investigation.

## 1.6 Conversation mechanics: asking, remembering, attaching

- **Guided input (`input_session`):** when an action needs inputs, the CEO asks **one question per turn**, written by code, with up to three real options plus "Other" and Cancel; every reply is parsed by code against that one question (no model). A bad answer re-asks with the reason; Back and Skip appear only where the backend offers them. Limits (CMO flows): 8 questions, 2 re-asks per field, 24 h idle expiry. Slots the seller already stated in their first message are extracted deterministically, echoed back and pre-filled.
- **Decision/conflict cards:** options are real candidates from the seller's own data, the recommended one first with its stated rule. Conflicts (two stored results that disagree on the same inputs, or two active manual inputs) are shown side by side, "neither has been chosen, averaged or combined".
- **Memory (`agent_memory`):** deterministic capture of business name, niche and where the seller sells; per-agent private notes (CMO last marketplaces, CI last competitor, CFO last GST basis, PI confirmed research). A remembered value is **offered as a choice**, never silently filled; everything is viewable and forgettable. Memory holds no money.
- **Shared findings ledger and needs broker:** agents' reported findings are recorded in a tenant-scoped append-only ledger with fixed trust wording ("reported, not verified"; no digits in agent text); the needs broker lets the CEO chain a follow-up ("the description along with the GST %") through rule-routed catalog needs.
- **Attachments:** files (images, PDF, CSV/XLSX) are stored tenant-scoped and append-only; type is decided from content. They reach the composer only as delimited untrusted quotes, and reach agents **by reference** (`attachment_id`), never as bytes through a model. Only operator-controlled model endpoints may receive an image.
- **Agent attachment:** each investigation has an attached-agent set (the seller can wire agents in and out). The CEO orchestrates only attached agents; attachment never grants access; a detached agent's earlier findings stay visible as historical evidence.
- **Investigations:** the top-level unit; created only by explicit seller action (plus the WhatsApp first-contact exception, WhatsApp being unbuilt). Lifecycle `ACTIVE → RESOLVED` (seller-authored note, reopenable) and `ARCHIVED` (hides). The CEO may suggest resolving, never does it. Tenant-wide for members holding `agent.ceo` + `investigation.view`.

## 1.7 Approval workflow (plan cards)

Any action that is **metered or sends seller data outside Metrion** is held as a **stored plan** instead of running:

- The plan is built by **code** from the registry and validated slots; the LLM cannot write, approve or alter it.
- It is shown as a **plan card** in the chat: what runs, the exact frozen inputs, units, what leaves Metrion and where, attachment hand-off (file, type, receiving model), validity. A compact view shows 3–5 lines; full detail and the hash are behind "Details".
- **Approve/Decline are buttons on the card**, shown only while it is awaiting approval **and** only to the user who asked. Approve sends the plan id and its **hash**; the server recomputes the hash and refuses a mismatch. **Typing "yes" never approves.**
- The plan **expires after 30 minutes**. Any material change creates a **new plan** (new id and hash); the old one becomes `SUPERSEDED`. Permission, tenant ownership, entitlement and data are **re-validated at approval**. Potentially-duplicating work is never retried automatically; an uncertain outcome is reported as uncertain.
- States are append-only and audited with actor, time and reason: `AWAITING_APPROVAL`, `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED`. Declined/expired/superseded plans say plainly that nothing ran, was sent or used up.
- Decision playbooks have no exemption: a playbook needs approval exactly when one of its legs does. Image analysis is its own small 0-unit plan card, then the generation is a separate card.

## 1.8 What the CEO orchestrates for each specialist

- **CFO:** reads, the diagnosis/cash playbooks, the decision playbooks, GST lookup by permission (Route A via CFO; Route B the shared tier-3 lookup, always `PROVISIONAL`, can never become an override without `agent.cfo` + `financials.adjust`), and **data requests** — when a CFO leg lacks an input the CEO can collect (cost, quote, batch budget), it asks exactly that, saves after a confirm card through the CFO's own write path, closes the request and re-runs the question.
- **PI:** product research from chat (slot extraction, one plan covering discovery + supplier lookup, top-five, final case, summary with "View Detailed Research"); "is #3 worth stocking?" asks for a quote/budget only if none is stored and runs the CFO legs on the seller's confirmed numbers. See `PI_details.md`.
- **CI:** conversational competitor discovery/tracking/screenshot intake/confirmation/monitoring/alert settings via `ci_conversation`, check-box pick cards. See `CI_details.md`.
- **CMO:** CEO-first delegation, requirement questions, attachment by reference, in-chat plan approval, verbatim results; seeding from PI keyword themes and CI listing insights (brokered, labelled "not verified"). See `CMO_details.md`.

## 1.9 How answers are written

- **Pure reads** render from a fixed template — **no model call**.
- **Interpretation** uses one composition call: the model writes around `{{F#}}` placeholders; verbatim blocks (CMO copy, trend sources, GST rate/source/date/disclaimer, specialist narratives) and required disclaimers are inserted by code. Gate failure → `TEMPLATE_FALLBACK` (figures and blocks in a fixed layout; never a failing draft).
- **Advisory answers** use four labelled knowledge layers: K1 verified state, K2 seller-declared context, K3 seller documents (specified, not built), K4 general guidance. **K4 may support qualitative advice only — never a number.** Tax/GST/legal questions are not advisory (GST goes to the lookup routes; other legal/financial-advice questions get a limits statement).
- **Decision support** presents options that come from specialist outputs, comparison cells that are stored figures (the CEO never computes a delta), and a recommendation labelled **"CEO's judgement — not a verified fact"**, conditional whenever evidence is thin ("ready to buy" is never said when a cost is unknown).
- **Briefings** use the shape *what we found / why it matters / what to do next*; health is shown as **bands and verified figures only** — no composite 0–100 score, no projected uplift.
- **Business Q&A:** nine question types answered from stored results with code-written "Not stored yet" sentences.

## 1.10 Billing, permissions and security

- Permissions: `agent.ceo` plus `investigation.view` to view/continue (`investigation.create` to start) — a second-key gate added after an independent review found `investigation.view` alone could read transcripts. Per leg: the agent's key and any extras (`research.niche_run`, `service.gst_lookup`, `research.market_trends`, `catalog.view`, `financials.adjust` where a write is involved).
- One CEO conversation unit per user turn with defined outcomes (`CEO_UNIT_RULE_2`, spec §6.42): clarifications, planned/declined/expired turns cost nothing; the execution turn is metered once when it runs; system runs consume none. Specialist units are separate and visible.
- Tenant isolation: every CEO table is `FORCE` RLS; app role has no DELETE on audit tables; no endpoint accepts a tenant id; cross-tenant ids are a plain 404.
- A denial explanation names the missing capability only — never another tenant's data or an internal id.

## 1.11 Flow visualisation and audit

Every invocation writes an `agent_run`. A CEO turn row is written first; each leg is a child (`parent_run_id`), including DENIED legs, so "Show flow" can list exactly what ran and what was refused and why — read from audit rows, not inferred.

## 1.12 Data the CEO stores (selected)

`investigation`, `investigation_message` (+ decision/plan/pick cards in `choices`), `investigation_turn` (classifier result, safety result, stage timings), `investigation_finding` (references + a display snapshot), `investigation_agent` (attachment), `investigation_attachment`, `investigation_plan` and its append-only event history, `agent_run`, `agent_memory`, `shared_finding`, `ceo_need`. Not yet created (V1-later): `ceo_goal`, `situation`, `ceo_decision`, `ceo_open_issue`, `ceo_followup`.

## 1.13 API surface (`/api/v1/ceo/*`)

Investigations (create/list/get/resolve/reopen/archive), turns (`POST …/{id}/turns`, with `UiAction`, optional explicit period, client request id), findings, per-turn events (SSE) and flow, agent attach/detach and availability, attachments, plan approve/decline, memory and shared-findings read/forget, `state/health`, form-support reads for the two decision playbooks.

## 1.14 Honest status and limits

*(From `docs/planning/ceo-build-status.md` and the specs. I did not re-run tests or models.)*

- **Model quality is the main open risk.** The only measured baseline (`qwen3:8b`, one run, a laptop CPU) had whole-case classifier accuracy of ~36–42% on the fixture set, a ~22% attempted-forbidden-execution rate, and a composer that obeyed injected instructions in 3 of 4 cases. Code (closed catalog, numeral gate, choke point) rejects what the model gets wrong, so these are model measurements rather than product-safety failures — but **no model is selected and no pass bar was met**. A second model (`qwen35-4b-q4`) is registered but unmeasured. The owner's partner was to run the 90%-lower-bound evaluation; it was not recorded as run.
- **Numeral-gate gap:** quantity words ("a third", "doubled", "half") pass the gate (7 expected failures pinned as `xfail`); tightening risks false positives and is an open decision.
- **Not built / V1-later:** goals and Brain 1 goal-progress, situations/detectors/Priority Engine, follow-ups and business-memory writes, proactive briefings, scheduled worker, WhatsApp (no BSP), seller-document RAG for the CEO (K3), cross-worker SSE/cache (needs Redis).
- **No signed-in browser run** of the Hub against the real backend was recorded in the build status; most Hub tests use a fake API.
- **Status documents are stale in places:** `ceo-approval-workflow.md` still says "nothing implemented" and `ceo-cmo-delegation.md` says "specification only", but the repository now contains `approval.py`, `approval_gate.py`, `approval_run.py`, `plans.py`, `cmo_delegation.py`, `pi_research.py`, `ci_conversation.py` and a working `PlanCard`. Enabling approval for production is gated on owner decisions the spec lists (e.g. staleness threshold F1, restating the earlier verification findings). Treat the code as the truth and re-verify before relying on a status line.
- Operator configuration without defaults (a missing value refuses rather than guessing) includes `CEO_LLM_MODEL`, `CEO_LEG_TIMEOUT_SECONDS`, `CEO_PLAYBOOK_MAX_LEGS`, `CEO_MAX_CANDIDATE_PRICES`, `CEO_ATTACHMENT_*`, `CEO_NEEDS_MAX_PER_TURN`.

---

# PHASE 2 — The dashboard: the CEO Hub

**Route:** `/dashboard/ceo-hub` (`frontend/components/ceo/hub/*`, typed client `lib/ceo*.ts`, state hook `useCeoHub`).
**Nature:** the **only place the seller talks to any agent**. One conversation, not a dashboard of forms. The hub holds **no orchestration logic and no arithmetic**: it shows only the backend's stored, safety-gated messages and figures, and a test guards against numeric formatting, `₹` or scores in its source. Enforcement (attachment, permission, entitlement) is always server-side; the UI renders state and filters nothing for security. Theme tokens and visual design are not final.

## 2.1 Layout

```
┌───────────────────────────────────────────────────────────────────────────┐
│  CEO and agent canvas (draggable nodes on wires)         [ Add agent ]    │
│  CEO ── CFO / CI / PI / Slim CMO  (state, latest headline)                │
├───────────────────────────────────┬───────────────────────────────────────┤
│ LEFT work area                     │ RIGHT conversation (wider)            │
│  • what is running now (live)      │  messages, cards, plan card           │
│  • agents' results & figures       │  Welcome (when empty)                 │
│  • health strip                    │                                       │
│  • findings / execution panels     │ ┌───────────────────────────────────┐ │
│                                    │ │ + attach   message…        [Send] │ │ composer
│                                    │ └───────────────────────────────────┘ │
├───────────────────────────────────┴───────────────────────────────────────┤
│  Drawer: investigations · recent decisions · What I remember · agents' reports │
└───────────────────────────────────────────────────────────────────────────┘
```
Below the desktop breakpoint the work area and conversation become tabs so the conversation is never squeezed.

## 2.2 Components, one by one

- **Agent canvas (`AgentCanvas`):** the CEO and its four specialists as an n8n-style node graph. A **wire means "attached to the current investigation"** — not a workflow edge between agents. Each node shows its role, a state (ready / working with the action name / needs your input / off / locked — not entitled / no access), and the latest *complete* result's headline with its date (a newer partial or failed check appears on a separate "Latest check" line and never replaces it; with none: "No complete result yet"). Cards can be dragged (remembered in the browser) — dragging changes only where they are drawn. **Add agent** (top-right) wires a detached, attachable agent back in; locked or no-access agents are never offered. A small legend explains wires and dots; narrow screens draw simple connectors.
- **Welcome (empty conversation):** "What would you like to know?" with question-idea chips (these only fill the composer: "Why did my profit drop?", "Am I being paid what I am owed?", "Give me my business briefing", "What should I focus on this month?"), and three groups of **quick-action tiles**: *My business* (latest profit & loss, health bands, open leaks, inputs still needed, business briefing), *Competitors and products* (competitor prices, product research status, latest research report, listing content status), *Checks* (why did profit drop, anomaly check). Each tile is one catalog item sent directly with no classifier; a tile is disabled with a reason when its agent is off or unavailable. Two **Decide** buttons start the decision playbooks ("A competitor changed their price", "Should I stock a new product?"), and "Saved inputs" links open the cost / quote / budget run-forms.
- **Conversation:** the seller's and the CEO's messages (stored, safety-gated text), rendered with a tiny safe markup (headings, bullets, bold, links). Under answers: a **Key Insights** block when the saved result carries structured facts/figures (verbatim, never re-worded), buttons that open the agent page holding the full analysis (e.g. the research report), a line per follow-up lookup the CEO made for an agent, and follow-up chips (e.g. "Write titles for #n", "Is #n worth stocking?"). Quoted agent content is labelled as written by the specialist/public web. A one-line "shown in standard layout" note appears when the template fallback was used.
- **Cards in the conversation:**
  - **Decision card (`DecisionCard`):** the CEO's question with the recommended option first and its rule, up to two alternatives, "Other" (typed), and — only when offered — Back, Skip and Cancel. A choice is staged and sent with **Continue**, so a mis-click costs nothing. Answerable only while it is the latest message.
  - **Plan card (`PlanCard`):** compact lines and **Approve / Decline** (shown only while awaiting approval and only to the requester); a **Details** toggle shows the full frozen inputs, disclosure wording and hash; after a decision it shrinks to its title, with final-state wording ("Declined: nothing was run, sent or used up", "Expired…", "Replaced…").
  - **Pick card (`PickCard`):** check boxes / radios (e.g. competitors to track up to the free slots, categories to search, "which competitor is in this screenshot" with "None of these"). Pressing a button sends the text its template makes, so the same server checks apply as for typed text.
- **Composer:** the chat bar fixed at the bottom of the conversation column; Enter sends, Shift+Enter adds a line; **+** attaches files (type decided by the backend); typing or clicking with no open conversation starts one. Replies to any open question are typed here and parsed by the backend against that question.
- **Execution panel:** what the current task is doing, only from backend state — the live stage text and specialists running now (from the turn's event stream), finished turns with outcome and time, and "awaiting your input" for an unanswered clarification. There is deliberately no invented "Planning" state.
- **Findings panel (right/work area):** one card per agent finding, grouped under the question that produced it (newest first): who produced it, status (a failed or partial leg is shown plainly and never blocks the others), the verified figures with register chip and as-of date, notes, facts, what could not be checked, offers, conflict blocks verbatim, and provenance references one click away. A finding from a later-detached agent stays as historical evidence. **Show flow** opens the flow view.
- **Flow view:** how one turn was answered, read from audit rows — what ran, what was refused and why.
- **Health strip:** the business at a glance — CFO's GOOD / WATCH / AT-RISK bands and the latest saved profit & loss, each with its own date; a missing result says so instead of showing a number. No composite score, no projection.
- **Investigation list (left/drawer):** tenant-visible investigations, New investigation, archived behind a toggle, Resolve (seller note required), Reopen (resolved ones only), Archive. **Recent decisions** lists resolved conversations with the seller's own conclusion — nothing inferred.
- **What I remember (`MemoryPanel`):** shared items first, then each agent's own, verbatim; each can be forgotten.
- **Shared findings panel:** what the agents have reported to the CEO, with fixed trust wording ("reported, not verified" is never styled as verified); figures as references only; forgetting asks first and is lasting; entries from agents the member cannot use appear only as a count.
- **Decide panel (`DecidePanel`):** the two decision run-forms — price impact (competitor, SKU, fee reference, price basis, optional GST rate, current price, up to the configured number of candidate prices, four per-unit costs each as amount / "None (0), I confirm" / Unknown, with the saved cost shown with its date) and new product (SKU, units, history window, saved quotes with duties, budget). The browser sends only integer paise via an exact parser; running is refused until every cost is answered.
- **Deep links:** the hub accepts `?form=new-product|price-impact`, `?ask=…&about=…` (a pre-composed draft the seller sends — nothing runs on arrival) and `?ask=finding&finding=<id>` (an id only; the server validates it for this tenant).

## 2.3 States the Hub always renders

Empty / new, processing (with stage text), a finding arriving as each leg completes, partial or failed leg, clarification, plan awaiting approval, declined/expired/superseded plan, out of scope, completed, resolved (note shown, Reopen), archived (hidden by default but readable), detached-agent historical finding, locked (not entitled) and no-access agents, `TURN_IN_PROGRESS` wording, a send failure that keeps the draft, stale data and `CONFIG_MISSING` banners.

## 2.4 Display rules the Hub always follows

1. **The UI shows only what the backend stored and gated** — no client math, no rounding, no `₹` formatting of its own; figures arrive as display strings with their register and date.
2. **Missing means missing** — an unavailable figure becomes a named gap, never a zero or a guess.
3. **Verified vs reported vs estimated** are always visibly different (register chips, "reported, not verified", "CEO's judgement — not a verified fact").
4. **Nothing runs on arrival or on a typed "yes"** — quick actions send exactly one catalog item; metered work needs the plan card's Approve click.
5. **Agent output is quoted and labelled**; unverified web/agent text is never styled as the CEO's own words or as fact.
6. **Accessible:** a real modal drawer (focus trapped, Escape closes, focus restored), `aria` labels on regions and cards, keyboard operation, theme tokens (dark only today).

## 2.5 Other pages that surface CEO state

- `/dashboard/agents` (agent roster/availability) and `/dashboard/notifications` (merges competitor alerts and CFO data requests; situations are specified as a later third source) and the Overview page read stored results; they start nothing.
- Specialist dashboards (`/dashboard/pi`, `/dashboard/cmo`, `/dashboard/competitors`) are read-only libraries that link back into the Hub for every action; account, settings and data-management workflows (e.g. report upload on Finance) stay where they are.

## 2.6 Dashboard gaps (honest)

- **Reality vs spec on the canvas:** the spec describes a `+` on each node connector on hover and a per-node remove menu; the code's canvas comments say the seller does not remove or reconnect agents on the canvas itself and offers an **Add agent** button for detached agents. I did not run the page to confirm exactly what removal controls appear.
- No SSE-only transport — the Hub streams stage events with a polling fallback; cross-worker streaming needs Redis.
- Trend indicators on the health strip and a full "recent investigations and recommendations" panel were not built as specified; the Hub shows bands, latest P&L and recent resolved decisions.
- Not click-tested by me; the recorded build status says the signed-in browser flow had not been run end to end.
