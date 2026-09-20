# competitor-intelligence

Metrion's Competitor Intelligence agent (CI). Implements the direct-execution-path subset of
[`docs/specs/competitor-intelligence-agent.md`](../../docs/specs/competitor-intelligence-agent.md)
— see that spec's §1a for what is deferred in this pass (WhatsApp/CEO-routed invocation,
pending CEO agent implementation; the estimated-margin-range feature, pending a Brain-1
extension spec).

**Hard rule (CLAUDE.md):** this package computes no financial figure of any kind — margin,
fee, profit, tax or cost. The only arithmetic here is a price/availability delta between two
of CI's own observed snapshots (spec front matter B8, AC1). Any money-touching calculation
belongs in `packages/calc-engine` (Brain 1), never here.

**No live marketplace calls in tests.** The scrape/capture path depends on a `Fetcher`
protocol injected at the composition root; the test suite never constructs the real
`httpx`-based fetcher and cannot reach `amazon.in`, `flipkart.com`, or `meesho.com` — see
`src/competitor_intelligence/capture/fetcher.py`.

Repo layout decision recorded in `docs/planning/phase-1-readiness-review.md` item 2.5.
