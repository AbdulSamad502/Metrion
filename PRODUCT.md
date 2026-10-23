# Product

<!-- impeccable:product-schema 1 -->

## Platform
web (mobile-first: sellers mostly work from phones)

## Stack
Existing codebase: Next.js (App Router), React, TypeScript, Tailwind v4, Inter via next/font. Backend is FastAPI (separate).

## Users
Indian e-commerce sellers on Amazon, Flipkart and Meesho. They upload marketplace reports and want to see true contribution profit, where it leaks, and what to do next.

## Product Purpose
Metrion is an AI profit-optimization OS. It turns uploaded reports into contribution profit, finds the leaks and recommends actions. Success means a seller can trace every figure and trusts it. Recommend-only: it never writes back to a marketplace.

## Positioning
Every number is deterministic and traceable to its source report. LLMs explain figures and never compute them.

## Operating Context
- Reports are uploaded. There are no seller-side marketplace API integrations.
- Loop: ask, understand, trust, decide, act.
- Workspaces: CFO (with the Expense Tracker and Profit Calculator inside it), Competitor Intelligence, Product Intelligence, Slim CMO.

## Capabilities and Constraints
- All money is signed integer paise. The frontend does no money arithmetic and uses no floats.
- A missing input is "unavailable" or "not yet calculable", never zero and never a made-up estimate.
- Every figure shows source, period and status.
- Status vocabulary: Current, Stale, Processing, Estimated, Partial, Unavailable, Failed, Demo.
- Provenance types: engine-calculated, seller-entered, settlement-derived.
- Competitor Intelligence uses dated screenshot evidence, not live monitoring.
- Slim CMO is recommend-only and never publishes.
- GST is indicative, not filing-grade.
- The Expense Tracker is part of CFO, not an agent.
- The CEO Hub is out of scope for this design pass; it remains the central interface.
- Branding and UI are not final (docs/design/design_status.md): keep them configurable.
- Theme direction (dark vs light) is undecided. Do not treat near-black as permanent.

## Brand Commitments
Calm, premium, restrained green accent (current direction, not binding). Specifics are in DESIGN.md.

## Evidence on Hand
Reference images in docs/design/references and mockups in docs/design. Figures in them are sample content, not real data. No testimonials, customer logos or benchmarks exist, so none may be invented.

## Product Principles
1. Evidence first: provenance outranks polish.
2. Never invent a number.
3. Recommend, never act on a marketplace.
4. Restraint over spectacle in motion and effects.
5. Status is never conveyed by colour alone.

## Accessibility & Inclusion
WCAG 2.2 AA contrast. Respect prefers-reduced-motion. No pulsing or count-up animation. Touch targets sized for phones.
