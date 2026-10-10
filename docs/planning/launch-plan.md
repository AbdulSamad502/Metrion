# Launch plan: CEO and agents to startup level (2026-10-10)

Goal: every question gets the best appropriate, grounded answer; real sellers use it and benefit. Order below is build order. "Done" means verified, not written.

## Phase 0 — Prove it (parallel with everything)
- Owner's signed-in manual check of the Hub (scenarios in the build status).
- Partner runs the C7 evaluation (routing, missing-input, conflicts, grounded answers; ≥ 90% lower bound on ≥ 100 hold-out cases per metric). Add Hinglish and typo cases to the set.
- Real PI and CMO runs through chat with real keys. Five real sellers' reports checked by hand.
- Full backend suite once, alone; production frontend build.

## Phase 1 — Complete the chat product
1. **Memory (spec `agent-memory.md`)** — private per agent + one shared. *Built first: it fixes "what is my business name", makes every follow-up smarter, and is a differentiator.*
2. **Model speed** — measured: `qwen3:8b` ≈ 15 s per unrecognised message on this laptop (4 GB GPU: it spills to CPU); the installed 4B ≈ 6.5 s. Pick by the evaluation, not by feel (see recommendations in the build status).
3. **CFO from uploaded reports in chat** — import settlement/order reports through the trusted pipeline, then answer profit questions on them.
4. **CI research from chat** — competitor research, image upload, price comparison.
5. **CMO market trends** — preview, confirm, run.
6. **Persistent task list** — running / blocked / failed, survives refresh, retry.
7. **Image reading** for CMO and CI.

## Phase 2 — Seller product
Onboarding and a guided first win; weekly WhatsApp/email summary (BSP); Hinglish and Indian-format language support; empty/error states in plain words; "where this came from" on every figure.

## Phase 3 — Operate
Deployment config (all no-default limits), multi-worker streaming (Redis), Razorpay plans matching built caps, monitoring and cost per seller, security and isolation review on production-like data, backup/restore drill, privacy policy and terms.

## Phase 4 — Launch carefully
Closed beta 10–20 sellers → fix real misses → prove value (money found per seller) → capped paid launch, watched daily.

## Principles that do not change
LLMs explain, never compute money; every figure cites a ref; missing is UNAVAILABLE not zero; tenant isolation is existential; the CEO only recommends.

## Agent dependency map (2026-10-10, from the agent specs and the build)
Rule from the specs: agents never call each other. Every link below runs **through the CEO** (star topology), and money is only ever computed by the engine. Size: S = hours, M = about a day, L = several days.

**Built**
| Link | Seller says |
|---|---|
| PI -> CMO, PI -> CFO(GST) | "write titles for #3", "GST rate for #2" (numbered references) |
| CI -> CFO | "a competitor cut their price" (price-impact playbook) |
| CFO/PI -> new-product decision | supplier quotes + budget -> landed cost, ranking, batch size (saved SKU only) |
| Memory -> CEO, PI | business name, niche, markets; PI's last research offered as choices |

**Left to build**
| # | Link | What the seller gets | Spec status | Size |
|---|---|---|---|---|
| 1 | PI -> CFO: profitability of an idea | "is #3 worth stocking?" - supplier quote, cost, budget asked in chat, then landed cost, ranking, batch size; PI's stored feasibility estimate shown as an estimate | PI s6.8 "CFO batch-size handoff designed, not implemented" | M |
| 2 | CFO data requests -> CEO asks the seller | CFO says "I need your product costs"; CEO asks in chat, seller answers (and can attach the file), CFO re-runs | CFO s4 "data-request flow deferred to the orchestration spec" | M-L (a chat write; needs the same owner approval as the research brief) |
| 3 | Reports -> CFO from chat | attach settlement/order file -> trusted import -> profit answer | Phase 1 item 3 | L |
| 4 | CI -> CEO -> CFO fused alerts (Layer 2) | "Competitor X cut price 8%: your margin at that price would be ..." | CI C26 deferred "pending a real CFO agent" (CFO now exists) | M |
| 5 | CI research from chat (images / evidence upload) | "research my competitors" with screenshots | `ci.research_now` not wired (needs chat attachments to CI evidence) | L |
| 6 | CI -> CMO: listing insights | CMO writes titles/keywords using what competitors' listings use (keyword themes, differentiation gaps) | CMO spec s7 attachment path: CEO reads CI insights and passes them as declared fields | M |
| 7 | PI -> CMO: keyword themes | titles/hashtags seeded from the research's themes | not specified; propose in a spec | S-M |
| 8 | PI -> CI: who already sells #3 | CI discovery for an idea | CI C21 discovery exists; chat route missing | M |
| 9 | CMO market trends in chat | preview -> confirm -> run | CMO s8 routes exist; chat session missing | M |
| 10 | CFO -> CMO: thin margin -> improve the listing | "my margin is thin on SKU X: improve its listing" | not a spec'd link (CMO must never state margin); would be a CEO suggestion only | S (suggestion), design review first |
| 11 | CEO decision briefs | options from several agents compared side by side, one recommended with its rule | CEO s6.23 DecisionBrief | M |
| 12 | Goals, proactive detection, scheduled briefing | CEO notices anomalies and opens an investigation; weekly briefing; goal progress | CEO V1-later (ceo_goal, situation) | L |
| 13 | Private memory for CFO, CMO, CI | each agent remembers its own preferences (CMO brand tone; CFO usual period; CI tracked rivals) | agent-memory.md built; not populated | S each |
| 14 | WhatsApp: ask and answer through the BSP | the same conversation on WhatsApp | whatsapp-integration.md, not built | L |

**Forbidden by spec (do not build):** CMO consuming competitor prices; PI calling margin or competitor-margin functions; any agent-to-agent call; any LLM-computed money figure.
