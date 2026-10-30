# Metrion — Product and UI/UX Guide (for the design partner)

> Purpose: everything a designer needs to know about Metrion to make the UI/UX professional-grade, without reading the specs.
> **CFO is deliberately excluded** — the Profit & Finance agent and its page are not finished, so don't design from them. Everything else is described as it exists in the repository on 2026-10-21.
> Companion files in this folder: `PI_details.md`, `CMO_details.md`, `CI_details.md`, `CEO_details.md` (agent behaviour and per-dashboard detail). This file is the cross-cutting layer: product, users, rules, design system, navigation, patterns, states, gaps.
> Sources: `CLAUDE.md`, `docs/design/*`, `frontend/app/globals.css`, `frontend/lib/navigation.ts`, `frontend/components/ui/*`, the page components. Anything I could not confirm from code is marked **(unconfirmed)**.

---

## 1. What Metrion is

**Metrion is an AI profit-optimisation OS for Indian e-commerce sellers on Amazon, Flipkart and Meesho.** Sellers **upload** their marketplace reports (there are no marketplace API integrations) and Metrion turns those files into true contribution profit, finds money leaks, researches products and competitors, writes listing content, and recommends what to do next.

**The product loop:** **ASK → UNDERSTAND → TRUST → DECIDE → ACT**
- the seller **asks** in plain language,
- Metrion **understands** the question against *their own* data,
- every figure carries enough provenance to be **trusted**,
- the seller **decides**,
- and Metrion **acts** — but only as a *recommendation*. It **never writes back to a marketplace**.

**Trust is the load-bearing step.** The design principle that follows: *a number a seller cannot trace is worse than no number at all.* Most of the design decisions below exist to protect that.

### Who uses it
Small and mid-size Indian online sellers (often owner-operators) running one or more of Amazon / Flipkart / Meesho. Assume: busy, mobile-capable, not a finance specialist, uses INR, comfortable with WhatsApp, wary of tools that "guess" with their money. Language is English (Hinglish/regional not claimed). Prices are in rupees with Indian digit grouping.

### Tenancy and roles (affects what a screen may show)
One business account = one tenant (Clerk Organization). Members have roles/permissions per agent; some features are paid ("entitlement") and show as **locked** when the business isn't entitled. A member may lack permission for an agent ("no access"). Every page must therefore support: *available, locked (not entitled), no access (not permitted)* — see §8.

---

## 2. The agents (what the product "has")

The seller talks to **one** assistant (the **CEO**). Four specialists sit behind it. The seller never talks to a specialist directly — each specialist page is a **read-only library of what the CEO already produced**, with buttons that open the CEO chat.

| Agent | What it does for the seller | Page (nav label) | Detail file |
|---|---|---|---|
| **CEO** | Single conversational interface; understands the question, asks for what's missing, runs the right specialist, asks approval before anything costs quota, explains results | **CEO Hub** | `CEO_details.md` |
| **PI** — Product Intelligence | Finds product opportunities, evidence, commentary, supplier leads; shortlists the top 5 | **Products** | `PI_details.md` |
| **CI** — Competitor Intelligence | Finds/tracks competitors, reads screenshots the seller sends, reports price/stock/review changes | **Competitors** | `CI_details.md` |
| **CMO** — Slim CMO | Writes marketplace titles, listing copy, hashtags, answers catalog questions, builds market-trend reports | **Listings & Marketing** | `CMO_details.md` |
| CFO | Profit, cash, GST, leaks — **not finished; ignore for UI work** | Profit & Finance | — |

**Important consequences for the UI:**
- Menu and headings use **plain words**, not role names. "CFO/CMO/CEO" appear only inside pages that explain them (a deliberate decision).
- The specialist dashboards **contain no forms or generate buttons**. Anything that creates, uploads, confirms or changes data happens in the **CEO Hub chat**. Dashboards link into it (carrying ids, never content).
- Because of this, the **CEO Hub is the product's centre of gravity**; the other pages are "show me what's saved".

---

## 3. Non-negotiable product rules the UI must respect

These come from the project's hard rules. They shape visuals as much as copy.

1. **No invented numbers.** The UI never shows a hard-coded, estimated, placeholder or sample money figure. A missing value is shown as **"Unavailable / Needs a screenshot / Not calculated"** with the *reason* — never `0`, never blank. (The original mockups contain fabricated numbers such as "₹6,24,000" and "health score 82"; they are *layout reference only*.)
2. **No client-side money maths.** The browser never adds, rounds, converts or formats money itself (a test forbids `₹` formatting helpers in the CEO Hub source). Display strings arrive from the backend. If you design a chart or total, it must be fed by stored values.
3. **Provenance on every figure.** Anything numeric should be able to show *where it came from, how sure we are, and its date* (see the badge systems in §6.4).
4. **Recommend-only.** Nothing is published, posted or sent to a marketplace. Output is text the seller **copies and pastes**. Use "Copy", never "Publish/Post/Apply".
5. **Estimates are never styled as facts.** Verified, derived, manual, estimate and unavailable are always visibly different — and never by colour alone.
6. **Honest wording.** Never "trending", "bestseller", "in demand", "live", "real-time" or "tracking continuously". Use "opportunity candidate", "attention signal", "as of <date>", "from the screenshot you sent", "reported, not verified".
7. **Approval is a click, not a sentence.** Anything metered or sending data out needs the **Approve** button on a plan card; typing "yes" never approves.
8. **Missing ≠ nothing.** If a feed failed, say *"We could not check everything"*, not *"Nothing needs your attention"* (a bug already fixed once — keep the distinction in every empty state).
9. **Tenant isolation is invisible but absolute** — never show another account's data, ids or counts; a foreign id is just "can't find that".
10. **Branding must stay configurable.** All colours, type and logo come from tokens; don't couple logic to a look.

---

## 4. Design status (read before redesigning)

- `docs/design/design_status.md`: *"The logo, branding, colors, typography, and final UI/UX system are not finalized."* Treat everything below as **current implementation, not approved final design**. You have latitude — but keep it token-driven.
- `docs/design/frontend-design/` (a Claude Design handoff, `Metrion App.dc.html`) was declared the **authoritative visual reference** on 2026-09-17: dark theme, green accent, glass/blur cards, Inter.
- Visual references exist in `docs/design/Design-Overviews/` (`Dashboard`, `PI-Dashboard`, `CI-Dashboard`, `Slim-CMO-Dashboard`, `CFO-Dashboard` — ignore CFO) and `docs/design/references/2026-10-11/`. **Every name, figure, percentage and date in those images is sample content.**
- Owner direction already given for specialist dashboards: *follow the reference closely in layout and hierarchy, in Metrion's black/green/white theme; real saved data only; search, filters, copy and detail views allowed; no generation forms.*
- Locked, do-not-touch (owner constraints): the **original Metrion logo mark** and the **sidebar structure/logo**; the **landing hero direction** (dark base + neon Metrion green, two-column hero with dashboard visual on the right — "don't drift without them asking"); the exact black/green theme.
- Landing/auth/onboarding were not in the original design file; they were built to match its visual language.

### Theme: dark only (important correction)
`globals.css` sets `color-scheme: dark` and defines **no light theme and no theme toggle** (I found none in the code). Some specs and my earlier agent files mention "light and dark"; **today the product is dark-only.** If you want a light theme, that is new work: it needs a second token set (the tokens are already centralised, so it is feasible) plus contrast re-checks.

---

## 5. Design system as built (tokens)

All defined once in `frontend/app/globals.css` as CSS custom properties; components use `var(--token)`. Tune the whole system there.

### 5.1 Colour
| Role | Token | Value |
|---|---|---|
| Page background | `--bg-base` | `#020302` (near-black, slight green) |
| Panels / popovers | `--bg-panel`, `--bg-popover` | `#0D0B08`, `#14150F` |
| Cards (translucent) | `--bg-card`, `--bg-card-elevated` | `rgba(32,36,30,.30 / .40)` |
| Sidebar / header glass | `--bg-sidebar`, `--bg-header` | `rgba(24,27,23,.28 / .26)` |
| Borders | `--border-subtle / default / hover` | white at 6% / 11% / 14% |
| Hover fill | `--fill-hover` | white 5% |
| **Brand accent (green)** | `--accent`, `--accent-hover` | `#3ECF74`, `#5BDD8B` |
| Text on accent fill | `--accent-on-fill` | `#062010` |
| Accent borders / fills | `--accent-border-subtle/default/strong`, `--accent-fill-subtle/default` | green at 15/22/35% and 8/12% |
| Warning (amber) | `--warning` (+`-fill`, `-border`) | `#E7AC42` |
| Negative (red) | `--negative` (+`-fill`) | `#F16B61` |
| Positive | `--positive` | = accent |
| Info (blue, "inferred/derived") | `--info` (+`-fill`, `-border`) | `#5BA8FF` |
| Text scale | `--text-1` … `--text-8`, `--text-group-label`, `--text-inactive`, `--text-mint`, `--text-bright` | `#F7FAF6` (brightest) down to `#5E655B`; group label `#4E534B` |
| Locked / inactive | `--bg-card-locked`, `--connector-inactive` | for agent locked states |

**Colour semantics (keep consistent):** **green = confirmed / positive / primary action**; amber = needs attention/unverified; red = negative/gap/error; **blue = inferred/derived**; muted grey = unavailable/neutral. Green is reserved for confirmed/positive — don't use it for estimates. **Colour is never the only signal**: badges always carry text, and several carry a glyph/shape (see ProvenanceBadge).

### 5.2 Glass surfaces
Three levels over the near-black base: **1 BASE** (opaque), **2 GLASS** (panels, cards: `--glass-bg` white 3%, border white 7%, `blur(14px) saturate(120%)`), **3 ELEVATED** (selected, drawers: white 5%, `blur(18px)`). All white/black alpha so they never pick up a hue ("dark, neutral — never warm"). Fallback solids exist where `backdrop-filter` isn't supported (`--glass-fallback-bg #131313`).

### 5.3 Typography (Inter; Geist as fallback)
Dense, product-UI scale — sizes live in tokens and nowhere else:
`--fs-page-title 22 · headline 19 · section 16.5 · card-title 15 · body-lg 14 · body 13 · body-sm 12.5 · meta 12 · meta-sm 11.5 · micro 11 · nano 10.5 · metric 24 · metric-lg 40`. Weights 400/500/600/700. Labels use uppercase with `0.06em` tracking; metrics use `-0.01em`; body line-height 1.5, tight 1.25. Utility classes: `t-headline`, `t-card-title`, `t-body`, `t-body-sm`, `t-meta`, `t-meta-sm`, `t-micro`, `t-label`. `mt-num` is the numeric style.

### 5.4 Shared component classes (`mt-*`)
`mt-dash-card` (+ `--elevated`, `--accent`, `--locked`, `--interactive` with a hover sheen), `mt-btn`, `mt-chip`, `mt-tab(s)`, `mt-nav-item`, `mt-row`, `mt-table(-wrap)`, `mt-ledger`, `mt-section`, `mt-panel`, `mt-eyebrow`, `mt-content` / `mt-stack` (page rhythm), `mt-focus` (focus ring), `mt-skeleton`, `mt-spinner`, `mt-drawer-*`, `mt-input`, `mt-prov` (provenance chip). Landing-only motion helpers: `mt-reveal`, `mt-float`, `mt-glow-panel`, `mt-orbit-ring`, `mt-cta-glow`, `mt-badge-shimmer`.

### 5.5 Motion
Landing uses reveal-on-scroll, a logo intro, floating cards, glow pulses, orbit rings and a drawn-line effect. In-app motion is restrained: sliding nav indicator, drawer slide, skeleton shimmer, pulsing ports on running agents, fade-up. A global **`prefers-reduced-motion`** override exists. Don't add motion to data surfaces.

### 5.6 Iconography
A single custom 20×20 line-icon set (`Icon.tsx`, `currentColor`, stroke 1.6, decorative by default — pass a `label` when an icon stands alone): overview, ceo, products, competitors, orders, customers, finance, marketing, reports, agents, cart, settings, notifications, lock, check, plus, arrow, chevron, close, menu, collapse, logout, dot, trash, alert. *If you add icons, match this style.*

### 5.7 Reusable components (`frontend/components/ui`)
`Button`, `Card`, `MetricCard`, `Stat`, `Section`, `Tabs`/`TabPanel` (hash-synced), `DetailDrawer`, `EmptyState`, `LoadingState`, `ErrorNotice`, `FormField` (labels, password toggle), `CostInput` (amount / "None (0), I confirm" / Unknown), `AuthCard`, `StatusBadge` (tone: accent/warning/negative/info/neutral, optional dot), `ConfidenceBadge`, `EvidenceStateBadge`, `ProvenanceBadge`. Dashboard shell: `AppFrame`, `DashboardShell`, `Sidebar`, `Topbar`, `HeaderContext`, `ShellFrame`.

---

## 6. Information architecture and navigation

### 6.1 Sidebar (persistent app navigation)
```
START      Overview · CEO Hub · Action Center
BUSINESS   Products · Competitors · Profit & Finance · Listings & Marketing
SYSTEM     Agents · Settings
```
Page titles and menu labels share one constant so they can never disagree (`PAGE_COPY`). Browser tab titles are "`<Page> · Metrion`".

| Nav label | Route | One-line purpose (the page subtitle) |
|---|---|---|
| Overview | `/dashboard` | What is happening, what matters, and what to do next |
| CEO Hub | `/dashboard/ceo-hub` | Ask in plain words. Metrion answers from your data, or hands the question to the right specialist |
| Action Center | `/dashboard/notifications` | Competitor price alerts and information Metrion needs from you, each with its next step |
| Products | `/dashboard/pi` | Find product ideas, check whether they are worth stocking, and shortlist suppliers |
| Competitors | `/dashboard/competitors` | What the CEO has found about your competitors: prices, changes and what customers say |
| Profit & Finance | `/dashboard/cfo` | *(unfinished — out of scope for your pass)* |
| Listings & Marketing | `/dashboard/cmo` | Titles, listing copy, catalog answers and market research, for you to copy and never published for you |
| Agents | `/dashboard/agents` | The specialists behind Metrion: what each one does and whether it is available to you |
| Settings | `/settings` | Your account, business and notification preferences |
| (print) | `/reports/pi/{runId}/print` | Black-on-white printable research report, no app chrome |

Behaviour: active item comes from the URL; a single indicator slides to the active row; desktop sidebar **collapses to icons**; below the `lg` breakpoint it becomes a **drawer** (focus trapped, Escape closes, focus returns). The **CEO Hub keeps the navigation closed until asked** (overlay mode). A small **attention count** shows on the sidebar. Items without a real page render as inert "Soon" rows (never a fake screen). "Agent Cart" is deliberately not shown (no purchasing service yet). Mockup screens for Orders/Customers/Reports are placeholders ("Soon").

### 6.2 Pre-login / account pages
Landing (`/`), Sign in, Sign up, Forgot password, SSO callback, **Onboarding** (business name) — all under the `(marketing)` layout, auth by Clerk (Google or email+password). Settings has three tabs: **Account & security**, **Business**, **Notifications** (digest frequency Off / Daily / Weekly; sign-in methods Google / Email & password; password change with strength meter).

### 6.3 Landing page sections
Nav → Hero (two-column: copy left, dashboard visual right; trust points "No credit card required · Free trial for all agents · Built for Indian sellers") → Stats strip → Trust strip → About → Features → Agent flow → How it works → Why Metrion → Pricing ("Free while we're in early access — ₹0"; tiers will follow) → Final CTA → Footer. Marketing copy must obey §3.6 (no unsupported claims).

---

## 7. Page-by-page summary (what each screen holds)

(Deep detail for the four agent pages is in the companion files.)

- **Overview** — reading order is the design: (1) *Business state*: one sentence on what needs attention + a freshness line naming which saved results the page is built on; (2) *Profit snapshot*: the latest **saved** results exactly as presented by the backend (no headline profit number exists on purpose); (3) *What matters now*: decisions with a next step; (4) *Agent activity*: who is working and what they last did; right column: *Opportunities* and *Market watch*. Two columns on wide screens (7/5).
- **CEO Hub** — the product's core. Agent canvas on top; left work area (live status, agent results, health strip, memory); right conversation with composer fixed at the bottom; drawer for investigations/recent decisions. Cards inside the conversation: decision card, plan card (Approve/Decline), pick card (check boxes), key-insights block, follow-up chips. See `CEO_details.md` §2.
- **Action Center** — merges competitor price alerts and "information Metrion needs from you" (data requests), each with its next step.
- **Products** — read-only research library: history, current investigation with rank carousel, product information tiles, commentary, evidence, supplier lead, recommendation, old investigations, print page. See `PI_details.md` Phase 2.
- **Competitors** — product pills, "what to do next" bar, 4 KPIs, tracked-competitors table, awaiting-decision leads, price band, insights, verified changes, freshness, waiting-on-you, review insights, history. See `CI_details.md` Phase 2.
- **Listings & Marketing** — news cards, SEO titles with marketplace tabs and Recent/Frequently-used toggle, grounded copy pack, hashtags + compliance summary, detail drawer. See `CMO_details.md` Phase 2.
- **Agents** — roster of the specialists with a description, tier and availability state (available / locked / no access).
- **Settings** — see §6.2.

---

## 8. State and pattern catalogue (design every one of these)

Every data panel needs all of: **loading** (skeleton/`LoadingState`), **empty** (explains *why* and *what to do*, with a link into the CEO), **error** (retryable, plain language — a failed load is *not* "no data"), **partial/degraded**, **stale** (shown, flagged with date, never hidden), **unavailable** (named reason), **locked** (not entitled — with an unlock path), **no access** (permission missing — disabled with the reason). Plus, for the Hub: processing with stage text, clarification, plan awaiting approval, declined/expired/superseded plan, out-of-scope, resolved/archived investigation, detached-agent historical result, send failure that keeps the draft, backend down.

### 8.1 Trust and provenance vocabulary (reuse; don't invent new ones)
| System | Values | Used for |
|---|---|---|
| **Register** (`ProvenanceBadge`) — exactly five | **VERIFIED** (read from uploaded data) · **DERIVED** (calculated from verified figures) · **MANUAL** (entered by you, not checked) · **ESTIMATE** (not measured) · **UNAVAILABLE** (input missing) | any figure from the engine/CEO. Shape, border style and a glyph carry meaning, not just colour; tooltip explains |
| **Evidence state** (`EvidenceStateBadge`) | Observed · Inferred (blue) · **Needs review** (amber — AI-read, unconfirmed) · Confirmed (green) | competitor/PI values. Never show an AI-read value as confirmed |
| **Confidence** (`ConfidenceBadge`) | available / unavailable / gap | PI honesty labels; "available" is **not green** (most are estimates) |
| **Status** (`StatusBadge`) | tone accent/warning/negative/info/neutral, optional dot | general state pills; always with a text label |
| Verified / Unverified | competitor price | a price is *Verified* only after the seller confirms it |
| Freshness | Fresh / stale / unavailable (+ date) | evidence age; stale never hidden |
| Plan state | Waiting for your approval · Approved · Declined · Expired · Replaced | plan cards |
| Agent state | ready · working (action name) · needs your input · off · locked · no access | canvas nodes |

### 8.2 Recurring interaction patterns
- **One question at a time** in the Hub (decision card): recommended option first with its rule, ≤3 real options + "Other" + Cancel; Back/Skip only when offered; a choice is *staged* and sent with **Continue**.
- **Plan card:** compact 3–5 lines + Approve/Decline (requester only); full detail behind "Details"; shrinks to its title after a decision.
- **Pick card:** check boxes up to a free-slot limit (competitors), radios for "which one".
- **Copy-first:** results are text to copy; every copy emits a usage event; "Mark as used" only records the seller's statement.
- **Deep links into the CEO:** buttons like *Ask the CEO*, *Explain this*, *Verify price*, *Track this* open the Hub with a pre-composed message the seller sends; nothing runs on arrival. They pass ids only.
- **Source attribution:** hotlinked images always show *"image from <domain>"*; supplier/web items show their source label and "not verified".
- **Quoted agent text** is labelled ("Written by the specialist… read it before you use it").
- **Tabs** are real tab lists (marketplace tabs, settings tabs); **drawers** are modal-style (focus trapped, Esc closes, focus restored).
- **Dates:** show the *evidence* date, not "now"; "Published <date>" vs "retrieved <date>" are different and both shown when known; "publication date not stated" is a valid state.

---

## 9. Voice, copy and content rules

- Plain, calm, specific. Say what happened, what's missing and the next step. Prefer "Ask the CEO to…" to jargon.
- Banned or restricted words: *trending, bestseller, popular, in demand, live, real-time, continuously monitored, verified* (unless it literally is), *guaranteed, ready to buy, approved by the marketplace, compliant*. Say "attention", "candidate", "reported", "as of".
- "Reviews" must be qualified: **viewer / web commentary** (not verified buyer reviews — those don't exist in V1).
- Money is displayed by the backend in rupees; units/quantities from the engine are **"a budget ceiling, not a recommendation"**.
- Every estimate/commentary/search lead carries its disclaimer; disclaimers are never dropped to save space.
- Empty states are written for the first-time seller ("Nothing here is estimated or sample data").
- CFO-page headings containing implementation jargon ("deterministic signals + one narration call") were already flagged as to-be-replaced with plain words.

---

## 10. Responsive and accessibility requirements already in force

- **Breakpoints:** wide desktop (≥1280–1440 designed and measured), laptop, tablet 768, phone 360–390. The Hub is two columns on desktop and **two tabs** ("Conversation" / "Activity") below `lg`; the agent canvas switches from a fan of wires to a vertical spine when its container is narrow (container queries); quick actions scroll in one row on phones.
- **Touch targets:** 44 px for primary controls, ≥32–36 px for chips/inline actions on touch widths. Known remaining small targets: some inline links (24 px on desktop), native checkboxes (13 px; the label is the hit area).
- **Keyboard and screen reader:** visible focus ring (`mt-focus`), radio groups, `aria-pressed` toggles, `aria-expanded` expanders, `aria-current` on active tab/dot, `role="alert"`/`status` for messages, labelled tables/regions, sr-only labels. Modals/drawers trap focus.
- **Contrast:** an automated test (`textTokens.contrast.test`) protects the text tokens; re-measure if you change them.
- **No horizontal page scroll** at 360–390 px; long unbroken text and links must wrap (`break-words`).
- Only **text + glyph + shape** may carry meaning; never colour alone.

---

## 11. Known UI/UX gaps and opportunities (honest list)

From the project's own audits and my reading:
1. **No light theme** (see §4) — and the product is described as dark-only in CSS.
2. **Populated-state design is under-reviewed.** The last design campaign could only review pages with an API answering 503 and an in-memory demo; **no signed-in review of populated Products/Competitors/Listings pages was done**. Expect density and hierarchy issues once real data is present.
3. **CEO Hub left column is long** on 1280–1440 px screens; a thread is only ~289 px tall at 360×800.
4. **Overview has no headline profit number** by design (no portfolio-level endpoint exists); you'll need a considered way to give "the answer first" without inventing a number.
5. **Specialist dashboards depend on the chat for every action** — make the "ask the CEO" handoff feel effortless (pre-filled drafts, clear context chips) rather than like a dead end.
6. **Multi-select** isn't supported by the chat protocol (one value per question); check boxes exist only in the special pick card.
7. **Hub canvas controls:** spec describes `+` on connectors and per-node remove; the code offers an **Add agent** button and drag-to-rearrange (drag changes layout only, not behaviour). Decide what the canvas should communicate — a wire means *"attached to this conversation"*, not a workflow edge.
8. **Trend visuals are limited:** the CI price-history chart and a "your price vs market median" card are specified but not present; the CEO health strip has bands and the latest saved result, not trend indicators. Charts must only show stored data points (a line needs ≥2 verified points).
9. **WhatsApp** is a placeholder everywhere (alerts, evidence intake) — don't design flows that assume it works.
10. **Sidebar/logo shell** was not visually re-verified after the Competitors dashboard replacement.
11. Inconsistency risk: three different "confidence/state" badge systems exist (§8.1); consider a single visual family that still preserves the distinctions.
12. Print page (`/reports/pi/.../print`) needs a manual Chrome/Edge print check.
13. Some pages still use a few hand-written inline styles rather than shared classes.

---

## 12. Design do / don't (quick card)

**Do**
- Lead each screen with the answer or the next action; put detail behind expanders/drawers.
- Show the *date and source* beside every non-trivial fact.
- Give every empty state an explanation and a path (usually "Ask the CEO").
- Keep green rare and meaningful (confirmed/primary); use amber for "needs you".
- Preserve all five registers and the Verified/Unverified distinction visually.
- Design for the "unknown" state first — it is the common state.
- Keep tokens central; test dark UI with real-length text, long product titles, ₹ lakh/crore values.

**Don't**
- Don't show a number you can't trace; don't use sample data in shipped screens.
- Don't add generate/regenerate/"(N unit)" buttons to specialist pages.
- Don't imply live monitoring, marketplace publishing, or verified demand.
- Don't use colour alone; don't hide stale data; don't turn "no data" into "0".
- Don't change the logo mark, sidebar structure or landing hero direction without the owner.
- Don't add an agent-to-agent connection on the canvas (the architecture forbids it).

---

## 13. Quick reference — where things live

| Need | File / folder |
|---|---|
| All tokens | `frontend/app/globals.css` |
| Nav, page titles/subtitles | `frontend/lib/navigation.ts` |
| Shared UI components | `frontend/components/ui/*` |
| App shell | `frontend/components/dashboard/*` |
| CEO Hub components | `frontend/components/ceo/hub/*` |
| Specialist dashboards | `frontend/components/pi`, `ci`, `cmo` |
| Landing sections | `frontend/components/marketing/*` |
| Visual references | `docs/design/Design-Overviews/*`, `docs/design/references/2026-10-11/`, `docs/design/frontend-design/` |
| Design audits | `docs/design/ui-ux-phase1..4*.md`, `frontend-excellence-report-2026-10-12.md` |
| Brand assets | `docs/design/frontend-design/assets/metrion-mark.png`, `docs/design/exploratory/metrion-logo-reference.png` |
| Per-agent behaviour | `docs/agent-details/*_details.md` |

## 14. Questions worth asking the product owner (not decided in the repo)

1. Is a **light theme** wanted, and should dark remain the default?
2. Should the Overview get a **headline answer** (e.g. a profit statement) — and which backend endpoint will supply it?
3. Is the **final logo/typography** still Inter + the current mark, or will the rebrand change them?
4. Should the three badge systems be **unified** into one component family?
5. How should **locked** (paid) agents be presented — Agent Cart is intentionally absent today.
6. Which **chart types** are acceptable given the "stored points only" rule (e.g. price history, margin trend)?
7. What is the intended **mobile priority** — full parity, or the Hub plus read-only dashboards?
