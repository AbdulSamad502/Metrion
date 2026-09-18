# frontend

Metrion's Next.js (App Router) application, per [`CLAUDE.md`](../CLAUDE.md)'s stack decision.
Renders figures computed by the backend/engine only — never calculates or re-derives money
values client-side.

**Phase 3 Step 3 (auth):** scaffolded via the Clerk CLI (`clerk init`) into this directory
directly (not nested). Design tokens ported from
[`docs/design/frontend-design`](../docs/design/frontend-design/README.md) into
`app/globals.css`. Auth-only scope so far:

- `app/layout.tsx` — `ClerkProvider`, themed to Metrion's tokens; header shows
  sign-in/sign-up/user controls.
- `app/sign-in/[[...sign-in]]`, `app/sign-up/[[...sign-up]]` — Clerk's own components
  (I1: no parallel custom auth system).
- `app/onboarding/page.tsx` — the O1/O2 blocking business-name step Clerk doesn't provide,
  plus the Step 3 exit-check (calls the protected `/api/v1/ping` backend route once
  onboarding is `ACTIVE`).
- `lib/api.ts` — thin fetch wrapper attaching the Clerk session token as a bearer token for
  every backend call.

The full app shell (sidebar, Overview, CEO Hub, etc.) is deliberately out of scope until
each page's backend exists — see `docs/design/frontend-design/README.md` for what's
designed but not yet wired to real data.

Run with `npm run dev` (needs `.env.local` — see `clerk init`'s output — and the backend
running on `NEXT_PUBLIC_API_BASE_URL`, default `http://localhost:8000`).
