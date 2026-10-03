"""P3 orchestration over persistence. I/O layer (excluded from the deterministic-core purity test).

NOT in P3: HTTP, entitlement pre-checks and `metered_event` writes (P5). This layer returns what
was delivered and what a run bills; the route layer meters (`cmo_metering_key(generation_id)`).
"""
