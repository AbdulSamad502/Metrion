# Frontend Design — Read This First

**This folder is the AUTHORITATIVE frontend design reference for Metrion's application UI,
for now.** Confirmed by the user 2026-09-17. It supersedes anything in
`docs/design/exploratory/` and `docs/design/design_status.md` as a visual reference — do not
compare against or fall back to those for layout/visual decisions. `design_status.md`'s
underlying instruction (don't hardcode colors/branding into core architecture, keep it
configurable) still applies to *how* you implement these tokens, just not to *which* design
you implement.

## What's in this folder

- **`Metrion App.dc.html`** — the primary design source. A Claude Design handoff export
  (HTML/CSS/JS prototype, not production code). **Read this file in full before implementing
  anything it covers.** Don't skim it, don't render it in a browser or screenshot it —
  everything needed (colors, spacing, layout, copy) is in the source text.
- **`support.js`** — generated `dc-runtime` framework code (the prototype's fake
  React-like component runtime). **Not design content. Skip reading this** unless you're
  specifically debugging how the prototype's `{{ }}` bindings or `sc-if`/`sc-for`
  pseudo-directives resolve — the visual design lives entirely in the `.dc.html` file's
  inline styles and CSS variables, not here.
- **`assets/metrion-mark.png`** — the Metrion logo mark used in the sidebar and chat avatar.

## What this design covers

An **already-authenticated app shell**: sidebar navigation + header + 13 screens —
Overview, CEO Hub, Products, Competitors, Finance, Marketing, Agents, Agent Cart,
Notifications, Settings (Business/Marketplaces/WhatsApp tabs), plus placeholder ("Soon")
screens for Orders/Customers/Reports. Dark theme, green accent, glass/blur cards, Inter
font. Full page/nav list and the CSS variable token block are both in the `.dc.html` file's
`<style>` block — read them directly rather than relying on this summary for exact values.

## What this design does NOT cover

**No auth or onboarding screens exist in this design** — no login, signup, forgot-password,
or business-name-onboarding step. When building those (Phase 3 Step 3, `auth.md`), match
this design's visual language (same tokens, same card/button/input treatment) — do not
invent a different visual style for auth, and do not skip building them just because they're
not in this file.

## Critical implementation rule — do not skip this

**Every number in this prototype is fabricated mock data** (net profit ₹6,24,000, health
score 82, etc.), hardcoded into the prototype's fake component state for demo purposes. Per
`CLAUDE.md`'s hard rule, production code may never show an invented or hardcoded money
figure — a missing input is `UNAVAILABLE`, never a placeholder value, and every real figure
must cite an `engine_result_ref`/`estimate_ref`. Treat this design as a **visual/layout
spec only**: recreate the structure, spacing, colors, and interaction patterns pixel-accurately,
but wire every page to real data (or an honest empty/"no data yet" state) once its backend
exists — never to the mock values shown here.

## How to use this folder

1. Read this file first (you're doing that now).
2. Read `Metrion App.dc.html` in full for the specific page/component you're implementing.
3. Recreate the visual output in the target stack (Next.js/React/TypeScript per `CLAUDE.md`) —
   match what you see, don't copy the prototype's internal templating structure.
4. Cross-check `auth.md` (for auth/onboarding screens) or the relevant agent spec (for
   pages whose data comes from PI/CI/CFO/CMO/CEO) for what's actually allowed to be
   displayed and where the real data comes from.
