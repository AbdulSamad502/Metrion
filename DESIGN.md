# Design

## Principles
Operate mode: scanability and trust over expression. Brand lives in precise detail. Theme direction (dark vs light) is undecided; the near-black below is today's implementation, not a commitment. Express every colour as a token so a light theme stays possible.

## Colour (verified against frontend/app/globals.css)
- Surfaces: --bg-base #0A0B0A, --bg-panel #0D0B08, --bg-popover #14150F, cards rgba(32,36,30,.30) / elevated .40
- Borders: --border-subtle rgba(255,255,255,.06), --border-default .11
- Text: --text-1 #F7FAF6, --text-2 #F2F4F0, --text-3 #DADFD6, --text-4 #C7CDC2, --text-5 #8F968C, --text-6 #8B9288 (all >=4.5:1, tested by app/textTokens.contrast.test.ts)
- Decoration only, never essential text or numbers: --text-7 #6B7268 (3.45:1), --text-8 #5E655B (2.85:1), --text-group-label #4E534B (2.17:1). Measured with the test's formula; not covered by the test.
- Accent --accent #3ECF74 (on-fill #062010)
- Warning --warning #E7AC42, Negative --negative #F16B61, Info --info #5BA8FF

## Semantic colour
- Green: verified or positive only.
- Amber: estimate or needs review.
- Red: a real risk.
- Blue: info only, never a status.
- Every status also carries a text label or icon.

## Status vocabulary
Current, Stale, Processing, Estimated, Partial, Unavailable, Failed, Demo. Each is a label plus icon, never colour alone. Demo content must always be visibly marked.

## Provenance
Every figure names its source type: engine-calculated, seller-entered, or settlement-derived, plus source report and period.

## Typography
Inter via next/font (Geist fallback). Four sizes only, across the whole app:
- 12px: labels and meta. This is the floor; nothing is smaller.
- 14px: body and controls.
- 20px: titles.
- 32px: metrics.
Weight, colour and spacing carry any further hierarchy, never a fifth size. Tracking: label 0.06em, metric -0.01em.

## Spacing
8-point grid. Gaps, padding and margins are multiples of 8 (8, 16, 24, 32, 40, 48); 4 is allowed only inside a control. Touch targets are at least 40px. No other values.

## Money display
- Integer paise only. The display helper (formatPaise) formats with Indian digit grouping (₹4,25,000) and never does arithmetic.
- Unavailable renders as "Unavailable" or "Not yet calculable", never 0.
- Numbers are right-aligned with tabular figures.

## Components
- Drawers trap focus and return it to the trigger on close.
- Empty states say what to do next.
- Signature interaction: the arrow that slides 4px on hover and focus (.mt-arrow; arrow only, label never moves).
- Mobile first: layouts and touch targets are designed for phones, then widened.

## Surfaces
Radius 14px (--radius-surface). Thin borders. Glass blur/sheen tokens exist; use sparingly on floating layers only.

## Motion
Restrained. Respect prefers-reduced-motion. No pulsing, no count-up numbers. Functional loading motion (skeleton, spinner) is allowed.
