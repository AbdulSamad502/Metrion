# UI/UX Phase 4 checkpoint: CEO Hub layout

Status: implemented (frontend only). Visual target: the CEO Hub reference mockup. The mockup is a visual reference, not data: no health score, product list or connection count from it is shown unless the backend reports it.

## What changed

- **Two columns, conversation dominant** (`CeoHubWorkspace.tsx`). Left (5/12): agent orchestration, task status, findings, business at a glance, memory. Right (7/12): the conversation with the composer fixed at the bottom of its own column. Below `lg` they become two tabs ("Conversation" / "Activity"); both stay mounted, so nothing is lost on a switch. Tab and chip controls are at least 44 px / 32 px.
- **Orchestration canvas** (`AgentCanvas.tsx`) is container-responsive (`@container`): a vertical spine with an elbow and a port dot per agent in narrow containers (the normal case beside the conversation, and on phones), the fan with node-port wires only when the container is at least 42 rem. Wires use the same meaning in both: solid = connected to this conversation, dashed = removed or locked, pulsing port or animated dash = running now (from the live event stream). A wire never reroutes anything; Remove/Connect only attaches or detaches the agent for future work in this conversation, as before (spec 6.22).
- **Execution activity** (`ExecutionPanel.tsx`) sits beside the canvas and states idle / awaiting input / running / completed / failed / not allowed / closed only from reported turn state. There is still no "planning" or "awaiting approval" state: the backend has none.
- **Messages** (`Conversation.tsx`): speaker label and timestamp on every message, readable maximum width, "Sending…" for an unconfirmed message. **Composer**: auto-growing, Enter sends, Shift+Enter adds a line, 44 px controls.
- **Mobile**: quick actions scroll in one row; the "agents connected" line is hidden below `sm`.

## Not implemented (and why)

- Pan, zoom, drag-to-connect: the backend has no routing graph to persist; a draggable connector would imply routing it does not have.
- Approval cards, plan cards, approve/reject: no approval endpoints exist on this branch. The layout leaves recommendations, plans, approval requests and results as separate message kinds to be added when the approval workflow is built; clarification answers and ordinary chat are never treated as approval.
- Overview page: unchanged in this checkpoint (it already reads only saved CFO results and the shared feeds).
