# Today's build: checkpoints, then evaluation (2026-10-10)

Rule for every checkpoint: spec line first, then code, then tests that fail without it, then the CEO regression for what it touched. A checkpoint is **done only when verified**; nothing is described as done before. After each one: a short report, and a commit only when the owner says push.

Assumption to confirm (owner can veto): the CEO may save data a seller **explicitly confirms** on a confirm card (the research brief is already approved; product costs and supplier quotes follow the same pattern). Nothing is saved without the confirm card.

## In scope today (about 8-10 hours of work)
| CP | What | Done when | Est. |
|---|---|---|---|
| **C1** | **PI -> CFO profitability** ("is #3 worth stocking?"): the new-product playbook accepts a PI idea; asks supplier quote, unit cost, shipping, budget in chat; saves them after a confirm card; runs landed cost, ranking, batch size; shows PI's stored feasibility as an *estimate* | tests: idea reference -> guided inputs -> confirm -> real engine run; cancel saves nothing; no money figure from a model | 2-3 h |
| **C2** | **CFO data requests -> CEO asks**: when a CFO action returns "I need X" (missing cost, missing budget), the CEO asks for exactly X, saves it after confirm, and re-runs the same question | tests: missing cost -> ask -> answer -> same task resumes and completes; no silent zero | 2 h |
| **C3** | **CI -> CFO fused alert**: "competitor X is at P; what is my margin at that price?" combines CI's observation with a CFO margin (engine) | tests: both legs, figures cited, neither agent's text copied | 1-2 h |
| **C4** | **Seeding CMO**: from a PI idea (keyword themes) and from CI listing insights (keyword themes, gaps), shown as quoted context labelled "not verified" | tests: themes offered as options in the CMO session, never filled silently | 1-2 h |
| **C5** | **CMO market trends in chat**: preview -> confirm -> run | tests: preview first, digest bound, cancel runs nothing | 1 h |
| **C6** | **Private memory** for CFO, CMO, CI (usual period, brand tone, tracked rivals) offered as choices | tests: isolation, forget, offered-never-filled | 1 h |
| **C7** | **Hub polish for the new flows**: confirm cards, follow-up chips ("Write titles for #2"), "What I remember" per agent | frontend tests, `tsc`, `eslint`, browser check | 1 h |
| **C8** | **Full regression + production build + docs** | CEO unit + integration green; frontend build clean; spec 6.35 / status updated | 1 h |

## Not today (stated, not hidden)
Reports to CFO from chat (several days; needs real sample files), CI research with image upload, goals / proactive alerts / weekly briefing, WhatsApp, onboarding, billing, deployment. Each stays on the launch plan.

## Then: evaluation (after C8)
1. **Partner's C7 run** (already designed): routing, missing-input, conflict handling, grounded answers, >= 90% lower bound on >= 100 hold-out cases per metric; command and report in the build status.
2. **End-to-end check of what we actually ship** (new, I run it): the shipped path is rules + classifier + guided input + composer, but the C7 harness uses its own prompts. I add a 60-80 case suite (English, Hinglish, typos) that runs the real `intent_router` and the real classifier prompt and scores: right route, no wrong refusal, no invented number, resumes the right task. Target: >= 90% routing, 0 safety failures.
3. **Model comparison on the same suite:** `qwen35-4b-q4` vs `qwen3:8b` (speed and accuracy) to settle which model ships.
4. **Owner's manual signed-in check** with the scenario list (kept in the build status).

## Stop rules
If a checkpoint runs past its estimate by 50%, I stop, report what is real, and re-plan rather than present partial work as finished.
