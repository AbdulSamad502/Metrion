# product-intelligence

Metrion's Product Intelligence agent (PI). Implements Phase 1 (standalone package) of the PI
build plan approved 2026-09-29 — see that plan for the full checkpoint sequence and
`docs/specs/product-intelligence-agent.md` for the feature spec. **This checkpoint
(Checkpoint 1 — Scaffolding) contains no discovery/ranking/review-derivation/supplier-lookup/
embedding/narration-safety business logic** — migrations, repository stubs, source-client
Protocols and the query cache only. Real logic lands in Checkpoint 2.

**V1 discovery sources: Tavily + YouTube only.** Google Ads Keyword Plan Idea Service demand
data was evaluated and dropped from this build at Checkpoint 0 (`KeywordPlanIdeaService`
requires Basic-tier access, which requires brand verification Metrion doesn't have ready) —
`sources/keyword_demand_client.py` and `product_candidate.demand_signal` stay in the schema
for later, unpopulated until that access exists.

**Hard rule (CLAUDE.md):** this package computes no financial figure of any kind. The only
money-touching interface it calls is `calc_engine.api.estimate_product_feasibility` (Brain 1,
`deterministic-engine.md` §5.13.2) — never its own arithmetic.

**No live external-API calls in tests.** `sources/tavily_client.py`,
`sources/youtube_client.py` and `sources/keyword_demand_client.py` each define a `Protocol`
seam; the test suite never constructs the real HTTP-backed client.

**Candidates are "opportunity candidates," never "trending products" or "bestsellers."** PI
has no sales-rank, no marketplace bestseller list, no verified-purchase data (see the PI
build plan §0a). This discipline is enforced structurally in `product_candidate.opportunity_label`
and checked in `reasoning/narration_safety.py` (Checkpoint 3).
