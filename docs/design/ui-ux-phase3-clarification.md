# UI/UX Phase 3 (clarification checkpoint) — what was built, and what the protocol can and cannot do

Date: 2026-10-09. Companion to `ui-ux-phase1-audit.md` and `ui-ux-phase2-notes.md`. Approval is specified separately in `docs/specs/ceo-approval-workflow.md` (not implemented).

## 1. The protocol, as inspected
- A card (`investigation_message.choices`) belongs to one CEO `CLARIFICATION` message and carries **one question**: `{version, kind, slot, options[]}` (+ server-side `pending`).
- A reply is `{id, option}` (an option key) or typed text. It is **one value per question**. Every answer is a turn; the next question is a new message.
- Multi-question flows exist only as the **guided input** sessions (`input_session.py`): the server holds the collected answers on the card (`pending.collected`), asks one field at a time, and writes "(N of M)" at the start of each question.

## 2. Requested controls vs. what is supportable
| Control | Status | How |
|---|---|---|
| Progress indicator | **Built** | Reads the backend's own "(N of M)" prefix (`lib/clarificationProgress.ts`). No prefix ⇒ no indicator (nothing estimated). |
| Back | **Built — needed a small additive backend change** | New option kind `BACK`, emitted by `input_session._card` on every question after the first; `advance(..., "back")` drops the last answered field **by field order** (jsonb does not keep key order) and re-asks it. No model call. The earlier answer stays visible in the thread. The UI shows Back **only if the backend sent it**. |
| Skip | **Built — backend flag, UI label** | The backend marks the options that record "unknown" on purpose (`skip: true`: the cost fields' "Unknown", GST "I do not know"). The UI offers them as **"Skip · Unknown"**, says what is recorded, and sends the real option (so the thread says *Unknown*). A required question without such an option has no Skip. |
| Continue / staged choice | **Built (frontend)** | A choice is staged; Continue sends. Typed "Other" text is kept while the seller changes their mind; blank/over-length is refused; Enter in the field continues. |
| Validation | **Built** | Blank refused, 200-character cap with counter; server-side parsing is unchanged and still re-asks with the reason. |
| Keyboard / a11y | **Built** | Native radio group (arrow keys), labelled progress bar, disabled states while a turn runs. |
| **Multi-select** | **Not supportable today** | A reply carries one option key or one text; every slot (`competitor`, `period`, `marketplace`, `sku`, …) is single-valued, and no flow needs several values. Showing checkboxes would be simulating a capability. |
| Edit an earlier answer arbitrarily | **Not supported** | Only Back one step (answers are append-only). |
| Several questions on one screen | **Not supported** | The CEO asks one question per message by design (§6.34). |

## 3. Proposal for multi-select (needs a spec decision, not built)
If a real need appears (e.g. "which competitors to compare"): the card would declare `{multi: true, min, max}` for a slot whose resolver accepts a list; the reply would carry `options: string[]`; the server validates each against the card's options and the slot's resolver and resumes the pending intent once. Backend changes: card schema (additive), reply body, resolver for list slots, tests. Frontend: checkbox rendering when `multi` is declared. Until a slot needs it, it stays out.

## 4. Files
Frontend: `components/ceo/hub/DecisionCard.tsx` (new; replaces the inline card in `Conversation.tsx`), `lib/clarificationProgress.ts` (+test), `lib/ceo.ts` (option type: `BACK`, `skip`), tests in `ceoHub.test.tsx`, `ceoInput.test.tsx`. Backend: `backend/src/backend/ceo/input_session.py` (+ `tests/integration/test_ceo_guided_input.py`). No migration; no change to the reply contract.
