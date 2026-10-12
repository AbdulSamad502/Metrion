-- R5 Stage 0b: read-only timing evidence for the target host (docs/planning/ceo-approval-r5-feasibility-audit.md §2.6, readiness §3.4).
-- READ-ONLY: SELECT statements only. Run as a role that can read the tables, ideally on the target host's database or a restored copy,
-- NEVER as a write path. It proposes no threshold: it reports what was observed. A seller-visible number is never derived from it.
-- Needed for reservation TTL sizing and any margin the owner wants on top of a lease; it is NOT needed to decide whether a leg is alive.
-- Tenant scope: agent_run / investigation_turn / pi_research_run are RLS tables. Run once per tenant with
--   SELECT set_config('app.current_tenant_id', '<tenant uuid>', false);   -- session-level, in a throwaway psql session only
-- or as a role that bypasses RLS on a copy that is not production.
-- HOW TO RUN IT SAFELY ON AN AUTHORISED TARGET HOST (needs the owner's authorisation; do not run it against production without it):
--   1. connect with a role that has SELECT only (never the application or migrate role) or add:  SET default_transaction_read_only = on;
--   2. wrap the whole file:  BEGIN READ ONLY;  \i ceo-approval-r5-measurement.sql  ROLLBACK;     (a write attempt then fails instead of succeeding)
--   3. RLS: the tables are FORCE-RLS, so a role without BYPASSRLS sees NOTHING until a tenant is set. Run per tenant with
--        SELECT set_config('app.current_tenant_id', '<tenant uuid>', true);   -- inside the READ ONLY transaction (true = transaction-local)
--      Zero rows from an un-set tenant context is silence, not evidence. Record which tenants were measured.
--   4. keep the output with the host, the date and the data window; a number without them cannot be used to size anything.
-- WHAT THE RESULTS CANNOT PROVE: that a leg is dead or alive (Q5), that nothing was ever stuck (an empty result on an empty or fresh database means nothing),
-- that a killed CMO leg ever existed (CMO writes no in-flight row, audit L6), or any staleness threshold. They are measurements to size reservation TTLs and
-- any optional margin; liveness is decided by the lease design (not by age), once the owner accepts one.
-- Caveats recorded by the audit: CMO writes its agent_run only at the end (no in-flight row, so it cannot show a killed run);
-- finished_at is written by the application clock; compare durations only within one host.

-- Q1. Completed leg durations per action (CFO, CI, PI choke-point legs; CMO gives duration only).
SELECT agent_id,
       trigger_ref,
       count(*)                                                        AS n,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p50_s,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p95_s,
       round(max(extract(epoch FROM finished_at - started_at))::numeric, 2)                                         AS max_s
FROM agent_run
WHERE finished_at IS NOT NULL AND parent_run_id IS NOT NULL
GROUP BY agent_id, trigger_ref
ORDER BY max_s DESC;

-- Q1b. Direct runs (a seller used the agent's own page, no CEO turn: parent_run_id IS NULL). Covers PI discover / supplier lookup and the CMO run rows.
-- The CEO anchor rows (agent_id = 'CEO') are excluded: their duration is the turn's (Q2).
SELECT agent_id,
       trigger_ref,
       count(*) AS n,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p50_s,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p95_s,
       round(max(extract(epoch FROM finished_at - started_at))::numeric, 2)                                         AS max_s
FROM agent_run
WHERE finished_at IS NOT NULL AND parent_run_id IS NULL AND agent_id <> 'CEO'
GROUP BY agent_id, trigger_ref
ORDER BY max_s DESC;

-- Q2. Whole-turn durations (database clock for created_at, application clock for completed_at; finalised turns only).
SELECT route,
       count(*) AS n,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY extract(epoch FROM completed_at - created_at))::numeric, 2) AS p50_s,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM completed_at - created_at))::numeric, 2) AS p95_s,
       round(max(extract(epoch FROM completed_at - created_at))::numeric, 2)                                         AS max_s
FROM investigation_turn
WHERE completed_at IS NOT NULL
GROUP BY route
ORDER BY max_s DESC;

-- Q3. PI discover run durations.
SELECT depth,
       count(*) AS n,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p50_s,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))::numeric, 2) AS p95_s,
       round(max(extract(epoch FROM finished_at - started_at))::numeric, 2)                                         AS max_s
FROM pi_research_run
WHERE finished_at IS NOT NULL AND started_at IS NOT NULL
GROUP BY depth;

-- Q4. How often, and how late, a leg finished AFTER its turn was finalised (audit L2: the deadline stops the wait, not the leg).
SELECT leg.trigger_ref,
       count(*)                                                                        AS late_legs,
       round(max(extract(epoch FROM leg.finished_at - t.completed_at))::numeric, 2)    AS max_seconds_after_turn
FROM agent_run leg
JOIN investigation_turn t ON t.agent_run_id = leg.parent_run_id
WHERE leg.finished_at IS NOT NULL AND t.completed_at IS NOT NULL AND leg.finished_at > t.completed_at
GROUP BY leg.trigger_ref
ORDER BY late_legs DESC;

-- Q5. Rows that are still non-terminal, with their age. A RUNNING row is NOT proof of a dead worker (a live late leg looks identical):
-- this is an inventory to look at, not a recovery rule.
SELECT 'agent_run' AS source, agent_id || ' ' || coalesce(trigger_ref, '') AS what, status,
       round(extract(epoch FROM now() - started_at))::bigint AS age_s
FROM agent_run WHERE status IN ('QUEUED', 'RUNNING')
UNION ALL
SELECT 'pi_research_run', depth, status, round(extract(epoch FROM now() - coalesce(started_at, created_at)))::bigint
FROM pi_research_run WHERE status IN ('QUEUED', 'RUNNING')
UNION ALL
SELECT 'investigation_turn', route, status, round(extract(epoch FROM now() - created_at))::bigint
FROM investigation_turn WHERE completed_at IS NULL
ORDER BY age_s DESC;
