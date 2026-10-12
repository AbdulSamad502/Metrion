# Report B: Frontend design campaign (2026-10-12)

## Sources inspected
1. Claude Design mockup `docs/design/frontend-design/` (README, tokens as used by `globals.css`).
2. The six reference images in `docs/design/references/2026-10-11/` (Overview, CFO, Competitors, Slim CMO, logo, variants): used for hierarchy (one answer first, calm summary tier, then detail), card composition and density. Every figure in them is sample content; none was copied.
3. Verity study and notes via `design-references-index.md`: principles used (one idea per screen, hierarchy from scale and luminance, restrained accent, honest states); exclusions respected (no invented proof, no "autopilot" claims, no waveform, no Verity branding).
Existing audits read: `ui-ux-phase1..4`, `frontend-roadmap-remaining.md`. The existing system already implements most of the mockup (tokens, glass layers, nav, Hub two-column), so the work targeted measured defects, not a restyle.

## Changes (all frontend, none touch backend behaviour, routes, approval gates or authorization)
CEO Hub
- `CeoHubWorkspace.tsx`: conversation column widened (`minmax(420px,38%)`, keeps the fan canvas at 1440 px); the duplicate "Quick actions" label row removed and the chips kept on one scrolling row; "Active specialists" row slimmed (test ids and "N/4 connected" text kept); task status now sits above the specialist canvas (a running or waiting task was a screen below the four tall cards); on phones the canvas follows the activity and findings, by document order (new `lib/useDesktopLayout.ts`), so keyboard order matches the screen; a clear alert with Retry when the conversation list cannot be loaded (backend unavailable used to look like a normal empty start); 36 px chips on touch widths.
- `Conversation.tsx`: compact title row (title no longer squeezed to "Demo con…" on a phone), long unbroken text and links now wrap (`break-words`), 36-40 px targets for Resolve/Archive/report buttons on touch widths. Measured at 1440x900: message area 250 px to 442 px.
- `ExecutionPanel.tsx`: a partly completed task is headlined "Partly completed" with an explanation (it was headlined plain "Completed" while the history row said partial: contradictory); raw route codes ("advisory") replaced by plain words.
- `HealthStrip.tsx`: "No saved results yet" is no longer shown as "not available, try again" when the request worked.
Shared: `ErrorNotice.tsx` (alert icon so status is not colour alone, focus ring, touch target), `Icon.tsx` (+`alert`), `FormField.tsx` (show-password target), `CopyTab.tsx` (wrap), `CreateTab.tsx` (target), `ReportingSections.tsx` (CFO preview date fields were clipped in a half-width card).
Overview (`app/dashboard/page.tsx`): **truthfulness fix**: when a feed failed the hero said "Nothing needs your attention right now" (unknown presented as none); it now says "We could not check everything", names what could not load, offers Try again, and a failed load no longer says "no saved results yet"; an empty bordered box under "What matters now" removed; 36 px link targets on touch widths.
Public-idempotency work in the frontend (`lib/ceo.ts`, `ceoModel.ts`, `useCeoHub.ts`) is described in Report A.

## `globals.css`
**Unchanged.** It stays the single source of tokens; no colour, size or font was added anywhere; no competing token layer. (It already has the reduced-motion override; none of the new code animates.)

## Verification
Browser (Claude in-app browser, real components over a temporary in-memory demo backend `app/dev-harness`, now deleted; everything on it was labelled DEMO; **not a signed-in session, so no real tenant data and no populated CFO/PI/CMO/CI pages were seen**): Hub in new, existing, partial, approval-refused, clarification, long-content, processing (a real send), memory-unavailable and backend-down states; Overview in error and empty-tenant states; every signed-in page (Overview, Action Center, Agents, CFO, PI, CMO, Competitors, Settings) with the API answering 503 at 390x844 and checked for horizontal overflow (none) and small targets. Hub overflow measured at 1440x900, 768x1024 and 360x800 (none; chip rows scroll inside their own scroller). 1280x800 viewed for the clarification state. Findings fixed as listed above. Not done: populated specialist pages, real keyboard/screen-reader walkthrough, contrast re-measurement (the existing `textTokens.contrast.test` passes).
Automated (after the last code change): `npx vitest run --maxWorkers=4` exit 0, **64 files, 439 tests passed**; `npx tsc --noEmit` exit 0 (first run failed only on stale generated `.next/types` pointing at the deleted harness; rerun after the build regenerated them: 0); `npx eslint` exit 0; `npx next build` exit 0. New tests: `ceoHubStates` (2), execution partial (1), overview unknown-vs-none (1), hub empty-saved (1), plus the id tests of Report A.

## CI worker setting
`.github/workflows/ci.yml` (uncommitted, never run, so no CI history) runs `npx vitest run --maxWorkers=4` on `ubuntu-latest`; runner size depends on repo visibility (4 vCPU public, 2 vCPU private) and cannot be read from here (no `gh`). Local controlled comparison (this 12-thread Windows machine, process pinned to N CPUs): 4 CPUs: 4 workers 101 s and 2 workers 135 s, both 434/434; 2 CPUs: 4 workers **failed (6 timeouts in 4 files)**, 2 workers 149 s, 434/434. Recommendation: `--maxWorkers=2` if the runner is 2 vCPU (private repo) and either if 4. **Not changed**: runner size unconfirmed, and local Windows results are not CI.

## Remaining UI defects and limits
Populated-state review of PI/CFO/CMO/CI needs a signed-in session; CFO page uses jargon headings ("deterministic signals + one narration call", "(calls the local LLM)") that should be plain words; many inline links keep a 24 px target on desktop (touch widths raised); native checkboxes are 13 px (their labels are the hit area); the Hub's left column is still long on 1280-1440 px screens; a thread is 289 px tall at 360x800.

## Repository safety
Pre-existing modified and untracked files untouched except where listed above; both stashes present; no commit or push; the temporary harness (my own untracked files) deleted; no backend, database or financial change in this campaign.
