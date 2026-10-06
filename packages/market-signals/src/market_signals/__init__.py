"""Neutral market-signal source layer (Tavily, YouTube, query cache, outbound throttle).

Shared by Product Intelligence and Slim CMO. No database, no tenant data, no dependency on
either agent. Extracted from `product_intelligence.sources` (plan: docs/planning/market-signal-extraction-plan.md);
the old import paths remain as shims that alias these very module objects."""
