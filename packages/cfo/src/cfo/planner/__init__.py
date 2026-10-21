"""AI Financial Query Planner — typed plans, closed catalog, deterministic validator (cfo-query-planner.md).

The model only ever fills a typed selection from the closed catalog; nothing it emits is executed as
code, SQL or a formula. Every money calculation stays in `calc_engine`.
"""
