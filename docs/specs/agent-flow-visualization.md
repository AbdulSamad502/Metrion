# Metrion — Agent Flow Visualization Specification

**Status:** Draft for review
**Prerequisites:** `ceo-agent-orchestration.md` (source of every `agent_run`, `investigation`, `investigation_message` row this spec renders) · `auth.md` (tenant/RLS scope for what a viewer may see).

**This is a frontend presentation spec.** It defines no new agent capability, no new calculation, and no new LLM call. It reads `agent_run` rows and renders them. If a rule here would require new backend computation, it belongs in `ceo-agent-orchestration.md`, not here.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Live flow view is hidden by default**, per conversational turn, revealed only by an explicit **"Show flow"** toggle attached to that turn's answer. It is never shown unprompted. | User instruction, this spec |
| C2 | **Branching diagram pattern.** A turn renders as: one CEO classify node → fan-out to either N parallel Brain 1 nodes (bundle) or one named-agent node → one synthesis node → the answer. A denied or clarification turn renders as a short two-node diagram, not the full pattern. | User instruction, this spec; `ceo-agent-orchestration.md` §6.4 | **Amended 2026-10-07 (CEO CP1-D1):** a `PLAYBOOK` turn renders as CEO classify node → **N parallel specialist nodes** (one per leg, all with `parent_run_id` = the CEO turn row) → synthesis node; Business State reads render as a read node, not an agent node. `SYSTEM` rows (V1-later) are out of this surface in V1 like direct-path rows (D5).
| C3 | **Historical drawer** — "How Metrion got this answer" — opens from an affordance on any past CEO-composed message, after the result is already delivered. It reuses the same diagram component as the live view, frozen at final state. | User instruction, this spec |
| C4 | This spec **owns no persisted data**. Everything rendered is derived, read-only, from `agent_run` / `investigation` / `investigation_message` as defined in `ceo-agent-orchestration.md` §5. | this spec |
| C5 | **No LLM involvement anywhere in this surface.** It is a rendering layer over already-composed structured audit data — the same `agent_run` table `ceo-agent-orchestration.md` §6.8 names as the source for its "Agents at Work" flow-visualization surface. | `ceo-agent-orchestration.md` C7, §6.8 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | **Turn correlation.** A single turn can produce several `agent_run` rows (one CEO row plus N parallel Brain-1 rows, or one CEO row plus one named-agent row). **Resolved:** `ceo-agent-orchestration.md` §5/§6.8 now carries a nullable `parent_run_id` on `agent_run`, null on the CEO's own turn-level row and set to that row's `id` on every row it fans out to. A turn's group is exactly `{anchor_run_id} ∪ {rows where parent_run_id = anchor_run_id}` — no heuristic needed. | Was: recommend adding `parent_run_id`; fall back to `investigation_id` + overlapping timestamps until it lands. Now: build every `FlowTurn` from `parent_run_id` directly. | Without a real key, two turns issued close together in the same investigation could not be reliably told apart. `parent_run_id` closes that gap; the timestamp-overlap heuristic is no longer needed for any row written after this lands. |
| D2 | Live-update transport | Short-interval poll (1–2s) of the turn's `agent_run` rows while any is non-terminal; stop polling once all reach a terminal `status`. Push (WebSocket/SSE) is a future upgrade, not required for V1. | Matches the low request volume of a single open flow view; avoids standing up push infrastructure before it's needed. |
| D3 | Node visual states | QUEUED (pending) / RUNNING (in progress) / COMPLETE / PARTIAL / FAILED / DENIED, mapped directly from `agent_run.status` | One-to-one mapping keeps the diagram an honest mirror of the audit row, never an interpretation of it. |
| D4 | Historical drawer entry point | A small affordance on each individual CEO-composed message, not a separate global history screen | Keeps "how did it get this answer" scoped to the answer the user is actually looking at. |
| D5 | Direct-path (fast-path) `agent_run` rows | **Out of scope for this surface in V1** — they carry no `investigation_id` and have no turn or diagram to attach to. A separate activity feed, if wanted, is future scope. | Fast path exists precisely to avoid CEO/turn overhead (`ceo-agent-orchestration.md` C2); forcing it into this diagram would misrepresent it as conversational. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | `agent_run` rows update with low enough latency for 1–2s polling to feel live | Low — worst case is a slightly stale node state, not incorrect data |
| A2 | Every `agent_run` row a viewer needs to group was written after `parent_run_id` landed; the timestamp-overlap heuristic (D1) still applies to any older row written before the migration | Low for new turns (grouping is exact via `parent_run_id`) — Medium only for historical rows predating the column, which fall back to the heuristic |
| A3 | Most users open the flow view for trust/verification, not as a primary reading surface | Low — justifies C1's hidden-by-default default; wrong only affects discoverability, not correctness |

---

## 4. Goals and non-goals

**Goals** — render a per-turn live flow diagram, hidden until explicitly opened; render the same diagram, frozen, from a historical drawer on any past answer; reflect `agent_run.status` honestly, including denied and partially-failed runs; update live nodes without a page reload while a turn is in flight.

**Non-goals (V1)** — any new backend table, calculation, or LLM call · visibility into direct-path (fast-path) runs · a global/admin-level activity feed across investigations · editing, retrying, or cancelling a run from this UI (strictly read-only) · final visual/motion design (this spec defines structure and behaviour; pixel-level design is a separate design pass, per `docs/design/design_status.md`'s rule that exploratory UI references are visual inspiration only, never a spec source).

---

## 5. Data model

No new tables. This spec defines a **read model** only, assembled client-side (or by a thin read endpoint) from existing rows:

```
FlowNode {
  agent_run_id, agent_id, trigger_ref,
  status,                      -- mirrors agent_run.status (D3)
  permission_check, entitlement_check,
  error_reason,
  started_at, finished_at
}

FlowTurn {
  anchor_run_id,               -- the CEO agent_run row for this turn (parent_run_id IS NULL)
  investigation_id,
  nodes: FlowNode[],           -- CEO node + fan-out node(s) + synthesis, per C2
  resolved_via_parent_run_id: bool   -- true when built from parent_run_id; false only for legacy rows predating the column, grouped via D1's timestamp heuristic
}
```

A turn is assembled by selecting the anchor row (`agent_id = CEO`, `parent_run_id IS NULL`, matching `investigation_id`) and every `agent_run` row with `parent_run_id = anchor_run_id`; that full set becomes `nodes`. `resolved_via_parent_run_id` exists so the UI (and QA) can tell a reliably-grouped turn from a heuristically-guessed one — it is never hidden from tooling, even though it need not be shown to the end user.

---

## 6. Core rules

### 6.1 Live flow view (C1)
Every turn's answer renders with a collapsed **"Show flow"** control. Nothing about the diagram is visible until a user clicks it. Opening it while the turn is still running shows the live, partially-resolved state (§6.4); opening it after completion shows the final state directly, with no further updates needed.

### 6.2 Branching diagram pattern (C2)
- **Brain 1 bundle turn:** CEO node → N parallel branch nodes (one per Brain-1 call in the bundle, per `ceo-agent-orchestration.md` §6.4's starter catalog) → single synthesis node → answer.
- **Named-agent delegation turn:** CEO node → one branch node (the delegated agent) → synthesis node → answer.
- **Denied or clarification turn:** CEO node only, marked DENIED, or CEO node → a "clarification asked" terminal node. No fan-out is drawn for a path that never ran.
- The diagram never fabricates a node for a call that was not actually issued — one `agent_run` row (or its absence) is one node (or none).

### 6.3 Historical drawer (C3)
Opened from the per-message affordance (D4). Renders the same `FlowTurn` structure as the live view, in its final terminal state, plus a compact text list: agent, trigger, permission/entitlement result, timing. It is the same component as §6.2, not a parallel implementation — divergence between "live" and "historical" rendering is itself a bug.

### 6.4 Live status updates (D2)
While any node in an open `FlowTurn` is non-terminal, the client polls that turn's `agent_run` rows every 1–2s and updates node state in place. Polling stops the moment every node reaches a terminal status (COMPLETE, PARTIAL, FAILED, DENIED). No polling occurs for a turn whose flow view is not open (C1).

### 6.5 Denied and failed rendering (D3)
A DENIED node shows the exact failing check (`permission_check` or `entitlement_check`) and its stated reason, verbatim from the row — never a generic "something went wrong." A FAILED node shows `error_reason` the same way. A PARTIAL bundle (per `ceo-agent-orchestration.md` E3) shows the succeeded branches as COMPLETE and only the failed one as FAILED — the synthesis node still shows COMPLETE if synthesis itself succeeded on partial data; the diagram must not paint the whole turn red for one failed branch.

### 6.6 Direct-path exclusion (D5)
Direct-path `agent_run` rows never appear in this surface. There is no toggle, filter, or drawer that surfaces them here in V1.

---

## 7. AI requirements

**None.** This surface performs no classification, no generation, and no summarisation. Every field it renders already exists on `agent_run`, produced by `ceo-agent-orchestration.md`'s own Brain 1 / Brain 3 work. Introducing any model call here — even a "summarize this flow" convenience — would be new scope belonging to that spec, not this one.

---

## 8. Authorization and security

1. No new permission key is introduced. Viewing a turn's flow requires nothing beyond what already grants visibility into the parent `investigation` (tenant-wide by default, per `ceo-agent-orchestration.md` D1) — if a member can read the message, they can open its flow.
2. All reads are RLS-scoped exactly as `investigation`/`agent_run` already are (`ceo-agent-orchestration.md` §8.4); a cross-tenant `agent_run` id resolves the same as a cross-tenant investigation id — not found.
3. This view surfaces `output_refs`, `status`, timing, and check results only — never raw request/response payloads, and never marketplace review or listing text. `investigation_message.content` is the only free text ever shown, and it is already CEO-composed or member-authored, not raw scraped text (`ceo-agent-orchestration.md` §8.5).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Flow opened while the turn is still running | Live partial state shown; non-terminal nodes visibly pending/in-progress (§6.4) |
| E2 | Turn denied before any child run was issued | Diagram shows the CEO node alone, marked DENIED; no fan-out drawn (§6.2) |
| E3 | Bundle partially fails | Failed branch shown FAILED; other branches and synthesis shown per their real status, never blanket-failed (§6.5) |
| E4 | A legacy turn predates `parent_run_id` and D1's timestamp heuristic cannot confidently group its rows (e.g. two turns overlap in time) | Diagram shows "flow unavailable for this turn" rather than guessing and risking a wrong diagram — does not occur for any turn grouped via `parent_run_id` |
| E5 | Historical drawer opened on a turn whose messages have since been folded into `investigation.summary` | Drawer still renders correctly — it reads `agent_run` directly, independent of summary compression |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Resolved** — `parent_run_id` (D1) now exists on `agent_run` (`ceo-agent-orchestration.md` §5/§6.8). Remaining work is implementation only: the write path must actually set it on every fan-out row, and the read path must query by it. | Was: reliable turn grouping; no longer blocks this spec's logic |
| V2 | Live-update transport (D2) unimplemented | §6.4 |
| V3 | `ceo-agent-orchestration.md`'s bundle catalog (its V2) is incomplete, and no visual/motion design exists yet | Neither blocks this spec's own logic — this spec defines structure and state, not diagram content coverage or pixels |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | The flow view is never visible for a turn until "Show flow" is explicitly clicked (C1). |
| AC2 | A rendered diagram contains exactly one node per real `agent_run` row for that turn — no fabricated or omitted nodes (§6.2). |
| AC3 | The historical drawer and the live view render from the same component (C3). |
| AC4 | A DENIED or FAILED node always shows the real check name / `error_reason`, never a generic message (§6.5). |
| AC5 | A partially-failed bundle never renders as a fully-failed turn (§6.5, E3). |
| AC6 | Polling stops once every node in an open turn reaches a terminal status (§6.4). |
| AC7 | No direct-path `agent_run` row ever appears in this surface (D5, E6). |
| AC8 | No cross-tenant `agent_run` or `investigation` data is ever rendered (§8.2). |
| AC9 | This spec introduces zero new backend tables and zero new LLM calls (C4, C5). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | User never clicks "Show flow" | No flow data fetched or rendered (AC1) |
| T2 | Bundle turn with 3 parallel Brain-1 calls | Diagram shows CEO node + 3 branch nodes + 1 synthesis node (AC2) |
| T3 | Named-agent delegation turn | Diagram shows CEO node + 1 branch node + synthesis node (§6.2) |
| T4 | Turn denied for missing entitlement | Diagram shows CEO node only, DENIED, with the entitlement reason shown (AC4) |
| T5 | One of three parallel branches fails | Diagram shows 2 COMPLETE + 1 FAILED + synthesis COMPLETE (AC5) |
| T6 | User opens historical drawer on a 2-week-old answer | Same diagram renders correctly from `agent_run`, unaffected by summary compression (E5) |
| T7 | Two legacy turns overlap in the same investigation, rows predate `parent_run_id` | UI shows "flow unavailable" rather than a merged/incorrect diagram (E4) |
| T8 | Turn completes while flow view is open | Live nodes update in place without reload; polling stops at terminal state (AC6) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q2 | Poll vs. push (D2) — is WebSocket/SSE infrastructure planned soon enough to design directly against it instead of polling? | §6.4, future rework cost |
### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Default visibility of the live flow view | **Hidden by default**, opened only via explicit "Show flow" toggle (C1). |
| R2 | Diagram shape | **Branching pattern** — CEO node, fan-out to parallel reads or one delegation, synthesis node (C2). |
| R3 | Post-answer explainability surface | **Historical drawer**, reusing the live-view component, opened per past message (C3). |
| R4 | Whether this spec owns any backend data or LLM work | **No** — pure read/render layer over `ceo-agent-orchestration.md`'s `agent_run` (C4, C5). |
| R5 | `parent_run_id` addition (was Q1) | **Accepted** — `ceo-agent-orchestration.md` §5/§6.8 now carries nullable `parent_run_id` on `agent_run`, null on the CEO turn-level row, set to that row's `id` on every fan-out row. Turn grouping is exact for any row written after this lands (D1). |
