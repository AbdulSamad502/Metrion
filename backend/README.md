# backend

Metrion's FastAPI application — agents, orchestration, auth, and API surface, per
[`CLAUDE.md`](../CLAUDE.md)'s stack decision. Consumes `packages/calc-engine` for all
money calculation; never reimplements it.

**Phase 3 Step 2 (database schema):** `migrations/` owns the DDL for `tenant`, `app_user`,
`membership`, `whatsapp_binding`, `auth_audit` (`docs/specs/auth.md` §5.1),
`investigation`, `investigation_message`, `agent_run`
(`docs/specs/ceo-agent-orchestration.md` §5), and `whatsapp_template`, `whatsapp_message`,
`whatsapp_pending_action`, `whatsapp_alert_subscription`
(`docs/specs/whatsapp-integration.md` §5) — see `migrations/README.md`. Tenant isolation
(RLS) for these tables is verified in `tests/integration/test_rls_isolation.py`.

The FastAPI application code itself (routes, Clerk integration, the six-step auth chain) is
Phase 3 Step 3 and not yet implemented.
