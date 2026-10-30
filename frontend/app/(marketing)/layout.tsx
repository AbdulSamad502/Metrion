import { Show, UserButton } from "@clerk/nextjs";
import "@/components/overview/overview.css";
import "./auth.css";
import { DarkOnly } from "./DarkOnly";
import Link from "next/link";

/** Header for the public/auth-flow pages (landing, sign-in, sign-up, onboarding). The
 * signed-in app shell (`app/dashboard`) has its own sidebar layout and deliberately
 * doesn't use this — a marketing header + an app sidebar on the same page would be a
 * redundant nav surface. */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-auth flex min-h-full flex-col" style={{ colorScheme: "dark" }}>
      <DarkOnly />
      <header
        className="flex h-16 flex-shrink-0 items-center justify-between px-6"
        style={{ borderBottom: "1px solid var(--border-subtle)" }}
      >
        <Link href="/" className="flex items-center gap-2">
          <span role="img" aria-label="Metrion" className="mt-auth-mark" style={{ width: 32, height: 20 }} />
          <span className="text-sm font-bold" style={{ color: "var(--text-1)" }}>
            Metrion
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <Show when="signed-out">
            <Link href="/sign-in" className="text-sm font-semibold" style={{ color: "var(--text-4)" }}>
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className="rounded-xl px-4 py-2 text-sm font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Sign up
            </Link>
          </Show>
          <Show when="signed-in">
            <UserButton />
          </Show>
        </div>
      </header>
      {children}
    </div>
  );
}
