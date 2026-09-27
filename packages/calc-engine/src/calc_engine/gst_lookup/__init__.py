"""G2 — GST Applicability Lookup (deterministic-engine.md §8.4, §8.4.1).

A **research** feature, structurally isolated from the calculation engine (§8.4: "A research
feature. Structurally isolated from the calculation engine."). Nothing in this subpackage is
imported by `calc_engine.api.compute_metric` or any formula module — it produces a
`GstLookupResult`/`GstLookupNoMatch`, never a `MetricResult`, and never enters a calculation
automatically (L2). CFO-side wiring/acceptance flow is a later checkpoint (G3).

Distinct from `calc_engine.gst` (existing sales-line GST normalization/summary code, §8.1/§8.3)
— that module is untouched by this one.
"""

from __future__ import annotations
