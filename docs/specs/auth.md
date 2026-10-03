# Metrion — Authentication, Tenancy & Authorization Specification

**Status:** Draft for review
**Prerequisite:** `docs/specs/data-foundation.md` — `tenant_id` appears on every tenant-owned table
**Related:** `docs/specs/deterministic-engine.md` · `whatsapp-integration.md` (identity resolution, invoke/revoke, investigation-creation — see W10, §7.5, R3) · entitlement spec (not yet written)

**Security is a first-class requirement of this document, not a later hardening pass.** Metrion stores sellers' financial records. A cross-tenant leak is existential, so isolation is enforced at the database boundary and never by application code alone.

**This specification contains no LLM.** Authentication, tenancy, and authorization are entirely deterministic. No decision described here is ever made by, delegated to, or influenced by a model. Requests arriving through LLM-facing surfaces — CEO chat, WhatsApp — re-enter the same authorization chain (§7.1) with no elevation.

---

## 1. Confirmed decisions

Settled. Not reopened here.

### 1.1 Tenancy and team model

| # | Decision |
|---|---|
| T1 | One Metrion **tenant** = one business workspace. |
| T2 | A tenant has **one OWNER/TEAM_LEADER** and **zero or more PARTNERs**. Partners live inside the same tenant and never receive their own. |
| T3 | **No GSTIN, GST registration, marketplace credentials, or marketplace connections are ever required at signup.** |
| T4 | Metrion is **file-first**. GST information is extracted from uploaded reports where present; where a request needs missing information, Metrion asks the seller for the relevant report or detail at that moment. |
| T5 | Marketplace names (Amazon, Flipkart, Meesho) are **report-source metadata only** — never connected accounts. |
| T6 | Multi-legal-entity and multi-GSTIN management is **not built in V1**. The schema stays extensible; the feature does not exist. |

### 1.2 Identity

| # | Decision |
|---|---|
| I1 | Clerk is the identity provider. **No parallel custom authentication system is built.** |
| I2 | Supported: Continue with Google · email/password signup · email/password login · password reset via Clerk. |
| I3 | **Clerk Organizations are used from V1.** One Clerk Organization maps to one Metrion tenant. |
| I4 | Roles are Metrion-specific: `OWNER` (team leader) and `PARTNER`. No unrestricted enterprise RBAC. |
| I5 | Email/password users must **verify their email** before accessing business data, uploading reports, running agents, or consuming credits. |
| I6 | Google-authenticated users are treated as externally verified. |
| I7 | Unverified users may exist in a restricted onboarding state with no access to protected functionality. |

### 1.3 Onboarding

| # | Decision |
|---|---|
| O1 | The **business-name step is blocking**. A tenant cannot exist without it. |
| O2 | The Google display name is **never** silently adopted as the business name. |
| O3 | Business name is the only mandatory tenant field. GSTIN, GST details, and marketplace connections are not. |

### 1.4 Tenant isolation

| # | Decision |
|---|---|
| S1 | **PostgreSQL Row-Level Security *and* application-level tenant filtering.** Defence in depth. |
| S2 | Every tenant-owned table carries `tenant_id` where applicable. |
| S3 | Every data-access path applies tenant scoping. |
| S4 | RLS is the **final database-level boundary**. |
| S5 | FastAPI establishes authenticated tenant context safely per request/transaction. |
| S6 | The design must be correct under **pooled connections** — tenant context must not leak between requests. |
| S7 | Frontend filtering and hidden UI are **never** a security mechanism. |
| S8 | Missing tenant context **fails closed**. |
| S9 | Cross-tenant access is **denied by default**. |

### 1.5 WhatsApp identity binding

| # | Decision |
|---|---|
| W1 | **One tenant has exactly one active WhatsApp Business destination** in V1. |
| W2 | The destination is either the team leader's verified number or a dedicated WhatsApp Business number for the team. |
| W3 | Partners do **not** receive separate destinations. |
| W4 | WhatsApp is connected later through an explicit integration/opt-in flow — **never during signup**. |
| W5 | The destination is verified through the official WhatsApp integration process. |
| W6 | Inbound messages on a verified destination resolve to **exactly one tenant**. |
| W7 | A number already bound to a tenant **cannot** be claimed by another. |
| W8 | Rebinding requires explicit disconnection, authorization, and fresh verification. |
| W9 | Tenant identity is **never** resolved from an unverified phone number alone. |
| W10 | WhatsApp operates under the tenant's entitlement and permission rules. The team leader controls whether it is enabled and which capabilities are reachable through it. **This states the principle only.** Whether an inbound question opens an Investigation is **resolved** — see `whatsapp-integration.md` C7/§6.5 and `ceo-agent-orchestration.md` R7: yes, implicitly, when none is `ACTIVE`. Cap arithmetic on WhatsApp and behaviour at cap mid-thread remain open (readiness review 2A.7) and are specified in `whatsapp-integration.md`. |
| W11 | Partners cannot bypass assigned permissions via WhatsApp. |

---

## 2. Design decisions requiring review

My recommendations. Each restated in §12.

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Session strategy (resolves open item 2.17) | **Clerk-issued JWT verified against Clerk JWKS. No Redis session store.** | Two session stores means two sources of truth. Redis keeps cache, queue, and rate limiting — not sessions. |
| D2 | Tenant context transport | **`SET LOCAL` inside an explicit transaction**, never session-level `SET` | `SET LOCAL` is transaction-scoped and resets at COMMIT/ROLLBACK, making it safe under transaction-mode pooling (S6). |
| D3 | RLS enforcement strength | **`FORCE ROW LEVEL SECURITY`** on every tenant table; application connects as a **non-owner, non-superuser role without `BYPASSRLS`** | Table owners bypass RLS by default. Without this, RLS is decorative. |
| D4 | New partner default permissions | **Deny-all.** The leader grants explicitly. | Fail-closed by default (S8/S9). A partner who can see nothing is a support ticket; one who can see everything is a breach. |
| D5 | Permission storage | Clerk holds **membership and coarse role**; Metrion holds the **fine-grained permission grid** | Clerk's org roles are coarse. Metrion-specific permissions (I4) belong in Metrion's database, checked server-side. |
| D6 | Clerk to Metrion sync | **Signed webhooks** (signature verified) plus reconciliation on login | Webhooks can be missed, duplicated, or arrive out of order. Login-time reconciliation makes the local mirror self-healing. |
| D7 | Cookie contents | UI preferences and last-viewed state **only**. No auth material. | Auth lives in the Clerk-managed token. Resolves the planning-doc cookie question. |
| D8 | Background workers | Set tenant context from the **job payload** using the same `SET LOCAL` mechanism | Workers touch tenant data too. A worker without tenant context must fail closed, not run unscoped. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Clerk organization-scoped session tokens carry organization id and role claims | Medium — otherwise membership resolution needs a Clerk API call per request |
| A2 | Connection pooling runs in transaction mode | **High** — session-mode changes the leak surface; D2 remains safe either way |
| A3 | Clerk webhook delivery is at-least-once and may be out of order | Medium — D6 mitigates |
| A4 | One Clerk user may belong to multiple organizations over time | Medium — affects organization-switching behaviour |
| A5 | The WhatsApp Business destination has a stable provider-issued identifier, not only a phone number | Medium — affects the uniqueness constraint design |

---

## 4. Goals and non-goals

### Goals
- Authenticate via Clerk with Google and email/password
- Create exactly one tenant per business, gated on a business name
- Enforce tenant isolation at the database boundary, correct under pooled connections
- Provide a two-role, permission-grid authorization model evaluated entirely server-side
- Bind exactly one verified WhatsApp destination per tenant
- Fail closed everywhere

### Non-goals (V1)
- Multi-GSTIN or multi-legal-entity management
- Marketplace OAuth or credential storage
- Enterprise RBAC, custom role creation, permission inheritance
- SSO/SAML, SCIM provisioning
- Multiple owners per tenant
- Per-partner WhatsApp destinations
- Cross-tenant support or admin impersonation

---

## 5. Data model and interfaces

### 5.1 Tables

```sql
tenant (
  id                  uuid pk,
  clerk_org_id        text unique not null,
  business_name       text not null,         -- O1: mandatory
  country             char(2) not null default 'IN',
  currency            char(3) not null default 'INR',
  timezone            text not null default 'Asia/Kolkata',
  status              text not null,         -- ACTIVE | SUSPENDED | DELETED
  created_at          timestamptz not null
)

app_user (
  id                  uuid pk,
  clerk_user_id       text unique not null,
  email               text not null,
  email_verified      boolean not null default false,   -- I5
  auth_provider       text not null,         -- GOOGLE | EMAIL_PASSWORD
  display_name        text,
  created_at          timestamptz not null
)

membership (
  id                  uuid pk,
  tenant_id           uuid not null references tenant,
  app_user_id         uuid not null references app_user,
  role                text not null,         -- OWNER | PARTNER
  status              text not null,         -- INVITED | ACTIVE | SUSPENDED | REMOVED
  permissions         jsonb not null,        -- D4: empty object = deny-all
  invited_by          uuid references app_user,
  joined_at           timestamptz,
  unique (tenant_id, app_user_id)
)
-- Exactly one active owner per tenant:
--   unique index on (tenant_id) where role = 'OWNER' and status = 'ACTIVE'

whatsapp_binding (
  id                  uuid pk,
  tenant_id           uuid not null references tenant,
  provider_account_id text not null,         -- A5: stable provider identifier
  phone_e164          text not null,
  verification_status text not null,         -- PENDING | VERIFIED | DISCONNECTED
  verified_at         timestamptz,
  enabled             boolean not null default false,   -- W10, owner-controlled
  bound_by            uuid not null references app_user,
  created_at          timestamptz not null
)
-- W1: one verified binding per tenant
--   unique index on (tenant_id) where verification_status = 'VERIFIED'
-- W7: a destination cannot be claimed twice
--   unique index on (provider_account_id) where verification_status = 'VERIFIED'
--   unique index on (phone_e164) where verification_status = 'VERIFIED'

auth_audit (
  id, tenant_id, actor_user_id, event, subject, metadata jsonb, occurred_at
)
```

### 5.2 Permission grid

**What the `agent.*` keys mean.** An `agent.*` permission grants a member the right to use that agent's capability. **How** the capability is reached depends on which of two paths carries the request, and the two have different permission requirements.

| Path | What it is | Permissions required |
|---|---|---|
| **Conversational route** | An open-ended request to CEO, which decides which agent handles it. CEO owns all routing. | `agent.ceo` **and** the target agent's key |
| **Direct execution path** | A specific, pre-enumerated, non-conversational action the member chose explicitly — a dashboard button. No routing decision exists to make. | The target agent's key **only** |

**CEO remains the sole *conversational* interface, and the sole *router*.** A direct execution path is not an open agent endpoint and does not make an agent "conversationally reachable": it invokes one named, bounded action that the member selected themselves. Because the member has already chosen the action, there is nothing for CEO to route.

**Guardrail — direct execution paths are enumerated, never general.** Each one is registered explicitly, names the single action it performs and the single `agent.*` key it requires, and is reviewed as part of that agent's spec. There is no generic "call agent X" endpoint, and no direct path may accept free-form input. Anything open-ended is a conversational request and requires `agent.ceo`.

**Consequence:** `agent.cfo` without `agent.ceo` is *not* an unreachable grant. It permits any registered CFO direct action while denying every conversational CFO request. The UI reflects that split rather than preventing the combination.

Stored on `membership.permissions`. **An absent key means denied** (D4).

| Key | Grants |
|---|---|
| `dashboard.view` | Dashboard access |
| `files.upload` / `files.view` / `files.delete` | File and report management |
| `investigation.create` / `investigation.view` | Investigation management |
| `agent.ceo` | CEO access |
| `agent.pi` | Product Intelligence access |
| `agent.ci` | Competitor Intelligence access |
| `agent.cfo` | CFO access |
| `agent.cmo` | Slim CMO access |
| `report.download` | Report download |
| `financials.adjust` | **Create or supersede manual financial adjustments** — every field in the `deterministic-engine.md` §7.2.1 field registry, without exception. At time of writing that covers COGS override, discount-bearer override, RTO outcome, cancellation flag, fee-GST treatment toggle, return refund amounts, seller-supplied logistics costs, the `expense.*` pools (advertising, packaging, storage, logistics, other), `settlement.receipt` corrections and `supplier.quote` data. Also governs responses to OP1 agent-initiated data requests. **The registry is authoritative — a field added there is covered automatically.** These inputs change Contribution Profit. |
| `service.gst_lookup` | Trigger the shared GST Applicability Lookup (OP9) |
| `research.niche_run` | Trigger a paid niche-discovery research run |
| `research.market_trends` | Trigger the shared Market Signal Retrieval service (web/video trend signals) used by `cmo.market_trends` (OP17, `slim-cmo-agent.md` §6.8). *Added 2026-10-03.* |
| `whatsapp.use` | WhatsApp access |
| `usage.view` | Usage visibility |
| `billing.view` | Billing visibility |
| `team.manage` | Partner invitation, removal, permission assignment, integration configuration, team settings |

**OWNER holds every permission implicitly and is not configurable**, including `financials.adjust`. Only `PARTNER` rows carry a meaningful grid.

**`financials.adjust` is deny-by-default for PARTNER** and must be granted explicitly by the OWNER. A partner without it may still upload files and view figures, but cannot alter any input that moves Contribution Profit. Every adjustment records `created_by` (`deterministic-engine.md` §7.1), so authorship is always attributable.

**Shared-service keys** (`service.gst_lookup`, `research.niche_run`, `research.market_trends`) are granted independently of `agent.*`. Per OP9 these services carry their own entitlement caps, so permission and entitlement are evaluated separately here exactly as in §7.2.

### 5.3 Request interface

```
Authorization: Bearer <clerk-session-jwt>
```

Resolved per request into an immutable context:

```
AuthContext {
  app_user_id, clerk_user_id, email_verified,
  tenant_id, membership_status, role, permissions,
  onboarding_state
}
```

A request that cannot produce a complete `AuthContext` is rejected. **There is no partial context** (S8).

---

## 6. Core rules

### 6.1 Onboarding state machine

```
UNAUTHENTICATED
   -> (Clerk sign-in)
PENDING_EMAIL_VERIFICATION        -- email/password only; Google skips this (I6)
   -> (email verified)
PENDING_ONBOARDING                -- authenticated, no tenant yet
   -> (business name supplied; organization and tenant created)
ACTIVE
```

- `PENDING_*` states may reach only: session endpoints, the verification endpoint, the onboarding endpoint, and sign-out.
- Every other endpoint returns `403` carrying the state, and never partial data (I7).
- An invited partner joining an existing tenant skips business-name collection and becomes `ACTIVE` on acceptance.

### 6.2 Signup and onboarding flow (O1, O2)

```
Email/password  OR  Continue with Google
        |
        v
Clerk authentication
        |
   email/password -> verification required (I5)   |   Google -> verified (I6)
        |
        v
Determine organization / onboarding status
        |
   has organization? -- yes --> link tenant, load membership --> ACTIVE
        |
        no
        v
Collect business name          <-- BLOCKING; never prefilled from Google (O2)
        |
        v
Create Clerk Organization  ->  create Metrion tenant (1:1, I3)
        |
        v
Assign creating user as OWNER, status ACTIVE
        |
        v
Onboarding complete  ->  Dashboard
```

Organization and tenant creation is **atomic**, in a defined order rather than an either/or:

1. Attempt **rollback** — delete the orphaned Clerk organization.
2. If deletion fails, mark the organization **quarantined** and retry through the reconciliation path (§6.5).
3. Until resolved, the user remains in `PENDING_ONBOARDING` and entry is blocked.

A Clerk organization without a Metrion tenant is an invalid state and is never reachable by a user.

### 6.3 Session strategy (D1)

- Clerk issues the session token. FastAPI **verifies** it against Clerk's JWKS using cached, rotation-aware keys.
- **No Redis session store.** Redis retains cache, job queue, and rate limiting only.
- Token expiry and refresh are Clerk-managed. Metrion never mints its own auth tokens.
- Revocation is effectively immediate because `membership.status` and `permissions` are read per request (§7.1), independent of token lifetime.
- Cookies carry UI preferences only (D7).

### 6.4 Password reset

Delegated entirely to Clerk. Metrion exposes no password endpoints, stores no password material, and never receives reset tokens. A successful reset produces no Metrion state change beyond an `auth_audit` entry written from the Clerk webhook.

### 6.5 Clerk and Metrion synchronisation (D6)

Subscribed events: user created/updated/deleted · organization created/updated/deleted · organization membership created/updated/deleted · email verified.

- Webhook signatures are verified before any processing. Unsigned or invalid payloads are rejected and logged.
- Handlers are **idempotent** and tolerate out-of-order delivery (A3).
- On every login, local membership is reconciled against Clerk.
- Clerk is authoritative for **membership**; Metrion is authoritative for **permissions** (D5).
- Clerk-supplied data is never trusted for authorization without local reconciliation.

---

## 7. Authorization and security rules

### 7.1 The authorization chain

Every protected request passes all six checks, in order, server-side. Failure at any step denies the request.

| # | Check | On failure |
|---|---|---|
| 1 | **Clerk authentication** — token valid, unexpired, signature verified against JWKS | `401` |
| 2 | **Organization membership** — a `membership` row exists for this user and this tenant | `403` |
| 3 | **Active membership status** — `status = ACTIVE` | `403` |
| 4 | **Metrion role** — `OWNER` or `PARTNER` resolved | `403` |
| 5 | **Required permission** — the endpoint's declared permission is present in the grid | `403` |
| 6 | **Tenant ownership of the resource** — the resource's `tenant_id` matches context | `404`, not `403`, to avoid confirming existence |

**Frontend hiding is not a security mechanism** (S7). Every check runs server-side; the UI merely reflects the same grid.

**Both paths run the full chain.** A direct execution path (§5.2) enters all six steps identically. It differs only at step 5, where the required permission is the target agent's key alone rather than `agent.ceo` plus that key. A direct path never skips a step, never relaxes tenant scoping, and never accepts free-form input.

### 7.2 Permission and entitlement are separate gates

Two independent questions must both pass before an agent runs:

| Gate | Question | Source |
|---|---|---|
| **Permission** | *May this member use CFO?* | `membership.permissions` — this spec |
| **Entitlement** | *Has this tenant purchased CFO, and are credits available?* | Plan and agent cart — entitlement spec |

A partner holding `agent.cfo` inside a tenant that has not purchased CFO is denied by **entitlement**. An owner in a tenant that owns CFO always passes **permission**. They compose; neither substitutes for the other.

### 7.3 Tenant isolation implementation (S1 to S9)

**Schema**

```sql
ALTER TABLE <tenant_table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <tenant_table> FORCE  ROW LEVEL SECURITY;   -- D3: owners do not bypass

CREATE POLICY tenant_isolation ON <tenant_table>
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
```

**Database roles**

| Role | Use | Privileges |
|---|---|---|
| `metrion_app` | Runtime application and workers | Non-owner, non-superuser, **no `BYPASSRLS`** |
| `metrion_migrate` | Migrations only | Table owner; never used to serve requests |

**Per-request context (D2, S6)**

Each request opens an explicit transaction and sets context with `SET LOCAL`:

```
BEGIN;
  SET LOCAL app.current_tenant_id = '<uuid>';
  -- all queries for this request execute here
COMMIT;   -- context discarded automatically
```

`SET LOCAL` is transaction-scoped, so a pooled connection returned to the pool carries no residue. **Session-level `SET` is prohibited** — it is precisely the mechanism by which tenant context leaks between requests under transaction pooling.

**Fail-closed behaviour (S8)**

- When `app.current_tenant_id` is unset, `current_setting(..., true)` returns `NULL`, the policy predicate evaluates to `NULL`, and **zero rows** are visible.
- Because zero rows can be misread as "no data", the application layer **additionally raises** when it is about to query without tenant context. Both layers fail closed; neither is trusted alone.
- Writes are equally constrained: `WITH CHECK` prevents inserting a row under another tenant's id.

**Application-level filtering (S3)**

Tenant scoping is applied in the data-access layer independently of RLS. RLS is the boundary, not the implementation. A forgotten `WHERE` clause therefore becomes a bug that returns nothing — never a breach.

**Background workers (D8)**

Workers set tenant context from the job payload using the same `SET LOCAL` mechanism. A job without a resolvable tenant fails and is dead-lettered; it never runs unscoped.

### 7.4 Cross-tenant denial

- **No endpoint accepts a client-supplied `tenant_id`.** Tenant is derived solely from authenticated context.
- Resource lookups are always tenant-scoped. A cross-tenant identifier returns `404`, never `403`.
- Identifiers are UUIDs, never sequential integers.

### 7.5 WhatsApp binding security (W1 to W11)

- Binding is initiated by the **OWNER only** (`team.manage`), after onboarding, never at signup (W4).
- Verification runs through the official WhatsApp integration process (W5). A `PENDING` binding grants nothing.
- Uniqueness is enforced by partial unique indexes on `provider_account_id` and `phone_e164` among `VERIFIED` rows (W7).
- Inbound resolution maps the **verified destination** to exactly one tenant (W6). An unresolvable destination is dropped and logged, never guessed (W9).
- WhatsApp-originated requests re-enter the §7.1 chain. The channel cannot elevate what a member may do (W11).
- Disconnection sets `DISCONNECTED`, releasing the uniqueness constraint. Rebinding requires fresh verification (W8).

### 7.6 Auditing

Every security-relevant event is written to `auth_audit`: sign-in, email verification, tenant creation, partner invitation, acceptance, removal, permission change, role change, WhatsApp bind and unbind, and **every authorization denial at steps 2 through 6**.

---

## 8. Edge cases

| # | Case | Required behaviour |
|---|---|---|
| E1 | Google user has no business name | Blocking onboarding step; display name never adopted (O2) |
| E2 | Same email used for Google and email/password | Clerk resolves identity linking. Metrion keys on `clerk_user_id`, never on email |
| E3 | Email/password user never verifies | Remains `PENDING_EMAIL_VERIFICATION`: no tenant, no data, no credits (I5) |
| E4 | User abandons onboarding after Clerk sign-in | `PENDING_ONBOARDING`; no tenant exists; resumes on next login |
| E5 | Clerk organization created but tenant creation fails | Invalid state. Entry blocked; retried or quarantined (§6.2) |
| E6 | Partner invited but never accepts | `status = INVITED`; no access. Invitations expire, but the window — and whether it is configurable at all — depends on the invitation mechanism, which is undecided (Q2). |
| E7 | Owner removes a partner mid-session | Next request fails at step 3 regardless of token validity |
| E8 | Owner revokes one permission mid-session | Next request fails at step 5. Permissions are read per request and never cached in the token |
| E9 | Partner requests another tenant's resource | `404` (§7.4) |
| E10 | Request reaches the database without tenant context | Zero rows from RLS **and** an application-layer exception (§7.3) |
| E11 | Pooled connection reused across tenants | `SET LOCAL` discarded at COMMIT; no residue (D2) |
| E12 | Worker job lacks a tenant id | Fails and dead-letters; never runs unscoped (D8) |
| E13 | Clerk webhook arrives out of order or duplicated | Idempotent handlers; login-time reconciliation corrects (D6) |
| E14 | Clerk webhook missed entirely | Reconciliation on next login |
| E15 | Clerk outage | Unexpired tokens continue to verify against cached JWKS; new sign-ins fail. Degradation is announced, never silent |
| E16 | WhatsApp number already bound to another tenant | Claim rejected by unique index. The message names the conflict without disclosing the other tenant (W7) |
| E17 | Inbound WhatsApp from an unverified destination | Dropped and logged. Never resolved by phone number alone (W9) |
| E18 | Owner disables WhatsApp | Inbound and outbound stop immediately; binding retained for re-enable (W10) |
| E19 | Partner holds `agent.cfo` in a tenant that has not purchased CFO | Denied by **entitlement**, not permission (§7.2). The denial **may be rendered as a reduced payload** — e.g. `cfo-agent.md` §6.9's gated preview — rather than a bare error. The capability is denied either way; only the presentation differs. Provisional (`cfo-agent.md` Q13) |
| E20 | Attempt to create a second OWNER | Rejected by the partial unique index (§5.1) |
| E21 | Clerk user deleted upstream | Memberships suspended; tenant and its data preserved. **Provisional** — final retention and deletion semantics are deferred to the DPDP decision (Q9) and may supersede this. |
| E22 | The sole OWNER is deleted or leaves | **Undefined — open question Q3** |
| E23 | Client supplies `tenant_id` in a request body | Ignored entirely; context is server-derived (§7.4) |

---

## 9. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Clerk organization-scoped token claims** (A1) — confirm organization id and role appear in the session JWT | Step 2 without a per-request Clerk API call |
| V2 | **Pooler mode confirmation** (A2) — transaction vs session pooling in the chosen deployment | Validates D2; the deployment target is still unchosen |
| V3 | **RLS verified under the real pooler**, by concurrent multi-tenant load rather than unit tests | S6 — the failure mode appears only under connection reuse |
| V4 | **WhatsApp provider identifier stability** (A5) | The uniqueness constraint design in W7 |
| V5 | **Clerk data residency** — user identity data leaves India | DPDP posture |
| V6 | **Clerk pricing at projected monthly active users** | Cost model; free-tier limits are not contractual |

---

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No endpoint accepts a client-supplied `tenant_id`. |
| AC2 | With tenant context unset, every tenant table returns zero rows **and** the application raises. |
| AC3 | `FORCE ROW LEVEL SECURITY` is set on every tenant-owned table, and the runtime role lacks `BYPASSRLS`. |
| AC4 | Under transaction pooling with concurrent tenants, no request observes another tenant's rows. |
| AC5 | All six authorization checks execute server-side; no check exists only in the frontend. |
| AC5b | Both the conversational route and every direct execution path run the full six-step chain; neither skips a step. |
| AC5c | Every direct execution path is registered, names one action and one required `agent.*` key, and accepts no free-form input. |
| AC5d | No generic "invoke agent" endpoint exists. |
| AC6 | A permission revoked mid-session takes effect on the next request. |
| AC7 | An email/password user cannot upload, run an agent, or consume credits before verification. |
| AC8 | A tenant cannot be created without a business name. |
| AC9 | A Google display name is never written to `business_name`. |
| AC10 | Exactly one `ACTIVE` `OWNER` exists per tenant, enforced by database constraint. |
| AC11 | A verified WhatsApp destination cannot be bound to two tenants. |
| AC12 | Inbound WhatsApp from an unverified destination never resolves to a tenant. |
| AC13 | A WhatsApp-originated request receives no capability beyond the member's grid. |
| AC14 | Permission and entitlement are evaluated independently, and both must pass. |
| AC15 | Metrion stores no password material and mints no auth tokens. |
| AC16 | Unsigned or signature-invalid Clerk webhooks are rejected. |
| AC17 | Cross-tenant resource access returns `404`, never `403`. |
| AC18 | Every authorization denial at steps 2 through 6 is audited. |
| AC19 | A worker job without a tenant id fails closed. |
| AC20 | Cookies contain no authentication material. |

---

## 11. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Google signup, new user | Verified; blocking business-name step; tenant created; user is OWNER |
| T2 | Google signup, business name left blank | Onboarding cannot complete; no tenant created |
| T3 | Email/password signup, unverified | `PENDING_EMAIL_VERIFICATION`; upload, agents and credits all denied |
| T4 | Email/password signup, then verified | Proceeds to the blocking business-name step |
| T5 | Password reset via Clerk | Succeeds; no Metrion password state; audit entry written |
| T6 | Owner invites partner; partner accepts | `PARTNER`, `ACTIVE`, **deny-all** permissions (D4) |
| T7 | Partner with deny-all opens the dashboard | `403` at step 5 |
| T8 | Owner grants `dashboard.view` only | Dashboard loads. No `agent.*` key held, so every agent request — conversational or direct — returns `403` at step 5 |
| T8b | Owner grants `agent.cfo` but not `agent.ceo` | **Registered CFO direct actions succeed.** Every conversational CFO request returns `403` (no `agent.ceo`). Not an unreachable grant (§5.2) |
| T8e | Owner grants `agent.ceo` but not `agent.cfo` | CEO responds but refuses to route to CFO; `403` at step 5 for the CFO portion |
| T8f | Direct path invoked with free-form input | Rejected. Direct paths accept only their enumerated parameters (§5.2 guardrail) |
| T8g | Attempt to reach an agent through an unregistered direct endpoint | `404`. No generic agent endpoint exists |
| T8c | Partner without `financials.adjust` attempts a COGS override | `403` at step 5. Upload and view remain permitted |
| T8d | Owner grants `financials.adjust`; partner overrides COGS | Accepted; `manual_adjustment.created_by` records the partner |
| T9 | Owner grants `agent.cfo`; tenant has not purchased CFO | Permission passes, entitlement denies (E19, AC14). Presentation of the denial — bare error or reduced payload — is the consuming spec's choice |
| T10 | Partner requests another tenant's file by id | `404` (AC17) |
| T11 | Client sends a foreign `tenant_id` in the body | Ignored; own-tenant data returned (AC1) |
| T12 | Query executed with no tenant context | Zero rows and an application exception (AC2) |
| T13 | Two tenants issue concurrent requests over a shared pool | Complete isolation; no residue (AC4) |
| T14 | Connect as table owner and read a tenant table | RLS still applies — `FORCE` verified (AC3) |
| T15 | Partner removed mid-session, reuses a valid token | `403` at step 3 (E7) |
| T16 | Permission revoked mid-session | `403` on the next request (AC6) |
| T17 | Attempt to create a second OWNER | Database constraint rejects (AC10) |
| T18 | Bind a WhatsApp number already verified elsewhere | Rejected; the other tenant is not disclosed (E16) |
| T19 | Inbound WhatsApp from an unverified number | Dropped and logged (AC12) |
| T20 | A WhatsApp-originated request (`CONFIRM` reply or session free text) is processed | Resolves to exactly `bound_by`'s (the OWNER's) real `membership.permissions` and re-enters the unmodified §7.1 chain — no separate WhatsApp trust level, no capability beyond that member's own grid (AC13, `whatsapp-integration.md` C8/§6.7) |
| T21 | Owner disables WhatsApp | Inbound and outbound stop; binding retained (E18) |
| T22 | Clerk webhook with an invalid signature | Rejected and logged (AC16) |
| T23 | Duplicate webhook delivered twice | Idempotent; no duplicate membership (E13) |
| T24 | Login after a missed webhook | Reconciliation corrects local state (E14) |
| T25 | Worker job without a tenant id | Fails and dead-letters (AC19) |
| T26 | Clerk organization created but tenant creation fails | Entry blocked; invalid state unreachable (E5) |
| T27 | Same email via Google and email/password | Handled by Clerk identity linking; single `clerk_user_id` (E2) |
| T28 | Expired token | `401` at step 1 |

---

## 12. Explicit open questions

Recorded rather than invented.

| # | Question | Impact |
|---|---|---|
| **Q2** | **Partner invitation mechanism** — Clerk's native organization invitations, or Metrion-issued invites? Determines whether permissions are assigned at invitation time or only after acceptance. | Medium |
| **Q3** | **Sole-owner departure or deletion** (E22) — ownership transfer, tenant suspension, or tenant deletion? Currently undefined and data-bearing. | Medium |
| **Q4** | **Maximum partners per tenant.** Unbounded team size against per-tenant caps has direct pricing consequences. | Entitlement spec |
| **Q5** | **Shared caps across a team.** Caps are per tenant — CEO 30/month on free, *recorded as a provisional config value awaiting approval, not a settled price point*. A five-person team exhausts that in days. Per-member sub-caps, or first-come-first-served? | Entitlement spec |
| **Q6** | **Partner-created content on removal** — do a removed partner's investigations and uploads remain with the tenant? *(Recommended: yes; the tenant owns the data.)* | Low |
| **Q7** | **Session and token lifetimes** — accept Clerk defaults, or set explicit values? | Low |
| **Q8** | **Support and admin cross-tenant access.** Deliberately absent from V1. When needed, it must be designed as an audited, time-boxed, consented mechanism — never a `BYPASSRLS` role. | Deferred |
| **Q9** | **Account deletion and data retention** under DPDP — deletion semantics for tenant, users, and raw uploaded files. | Deferred |
| **Q10** | **Active-organization resolution and organization switching.** A3/A4 assume a Clerk user may belong to several organizations, and `unique(tenant_id, app_user_id)` (§5.1) permits one `app_user` to hold memberships across several tenants. But `AuthContext` (§5.3) carries exactly one `tenant_id`, and the spec defines no rule for which organization is active, how a member switches, what happens to in-flight investigations on switch, or which tenant a background job resolves to for a multi-tenant user. **Load-bearing for isolation.** *(WhatsApp inbound is unaffected — W6 resolves by verified destination, never by user.)* | 🔴 Blocks multi-tenant membership |

### Resolved — do not re-flag

Recorded so later specs and reviews do not reopen them.

| # | Item | Resolution |
|---|---|---|
| R1 | **Who may alter figures that move Contribution Profit** | **Resolved.** `financials.adjust` (§5.2): OWNER holds it by default; PARTNER only by explicit OWNER grant; deny-by-default. Covers **every field in the `deterministic-engine.md` §7.2.1 registry** (the authoritative key space), `manual_adjustment` creation generally, and OP1 agent-initiated data-request responses. **Not an open question.** |
| R2 | **Whether `agent.*` keys imply direct agent endpoints** | **Resolved (amended).** They do not imply *general* agent endpoints — there is no "call agent X" route and nothing open-ended bypasses CEO. They do permit **enumerated direct execution paths**: specific, non-conversational, pre-registered actions a member selects explicitly, requiring the target agent's key alone (§5.2). CEO remains the sole conversational interface and sole router. Supersedes the earlier absolutist wording, which conflicted with the locked fast-path decision (readiness §1, Interface) and with `competitor-intelligence-agent.md` C20. |
| R3 | **Whose permissions apply to an inbound WhatsApp message (was Q1)** | **Resolved by `whatsapp-integration.md` C8/§6.7.** The two readings Q1 posed were a false choice: W2's "dedicated WhatsApp Business number for the team" option does not require per-member phone verification, because `whatsapp_binding` never resolves an inbound sender to an individual member at all — it resolves to `bound_by`, the single member who bound the channel. Since binding is OWNER-restricted (§7.5), `bound_by` is always the tenant's OWNER in V1. Every WhatsApp-originated request re-enters the unmodified §7.1 chain against that member's real permissions. W11 ("partners cannot bypass assigned permissions via WhatsApp") holds trivially in V1 because no partner identity is ever attributed to a WhatsApp request to begin with. **Residual gap, not reopened here:** a partner with physical access to a shared-device binding can still send messages attributed to the OWNER — accepted as a named V1 trust boundary, tracked in `whatsapp-integration.md` §13 Q4, not this spec's open question. |

---

## 13. Future / V2 considerations

Explicitly **not** V1. Listed so the schema stays extensible without building them now.

- Multi-GSTIN and multi-legal-entity support (T6) — `tenant` gains child entities; the RLS model is unchanged
- Additional roles beyond OWNER and PARTNER, and custom role definition
- Per-partner WhatsApp destinations (relaxes W3)
- SSO/SAML and SCIM provisioning
- Multiple owners and ownership-transfer workflows
- Marketplace OAuth connections — **only** if the locked upload-only decision is ever deliberately reversed. This is not conditional today: upload-only is settled product shape, and §4 non-goals states it correctly.
- Audited support impersonation (Q8)
