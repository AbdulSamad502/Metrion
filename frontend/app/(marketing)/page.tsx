import Image from "next/image";
import Link from "next/link";
import { Show } from "@clerk/nextjs";

/** Branded landing — auth scaffolding only, per Phase 3 Step 3 scope. The full app shell
 * (sidebar, Overview, etc. from docs/design/frontend-design) is out of scope until each
 * page's backend exists. */
export default function Home() {
  return (
    <main className="relative flex flex-1 flex-col items-center justify-center gap-7 px-6 text-center">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(ellipse 620px 320px at 50% 30%, var(--accent-fill-subtle), transparent)",
        }}
      />
      <div className="relative flex flex-col items-center gap-7">
        <Image src="/metrion-mark.png" alt="Metrion" width={72} height={72} priority />
        <div>
          <h1 className="text-4xl font-bold tracking-tight" style={{ color: "var(--text-hero)" }}>
            Metrion
          </h1>
          <p className="mt-2 text-xs font-semibold tracking-[0.15em] uppercase" style={{ color: "var(--text-tagline)" }}>
            Engine of Growth
          </p>
        </div>
        <p className="max-w-sm text-sm leading-relaxed" style={{ color: "var(--text-5)" }}>
          Upload your marketplace reports and see true contribution profit, the leaks
          costing you money, and what to do next.
        </p>

        <Show when="signed-out">
          <div className="flex items-center gap-3">
            <Link
              href="/sign-up"
              className="rounded-xl px-6 py-3 text-sm font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Get started
            </Link>
            <Link
              href="/sign-in"
              className="rounded-xl px-6 py-3 text-sm font-bold"
              style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}
            >
              Sign in
            </Link>
          </div>
        </Show>
        <Show when="signed-in">
          <Link
            href="/onboarding"
            className="rounded-xl px-6 py-3 text-sm font-bold"
            style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
          >
            Continue
          </Link>
        </Show>
      </div>
    </main>
  );
}
