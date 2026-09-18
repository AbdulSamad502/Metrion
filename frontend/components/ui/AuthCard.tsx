import Image from "next/image";
import type { ReactNode } from "react";

/** The glass-card auth shell — docs/design/frontend-design's card treatment
 * (blur, subtle border, radial accent glow) applied to a centered auth form. */
export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <main className="relative flex flex-1 items-center justify-center px-6 py-16">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 520px 320px at 50% 20%, var(--accent-fill-subtle), transparent)",
        }}
      />
      <div className="relative w-full max-w-[400px]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <Image src="/metrion-mark.png" alt="Metrion" width={40} height={40} />
          <div>
            <h1 className="text-xl font-bold" style={{ color: "var(--text-1)" }}>
              {title}
            </h1>
            {subtitle && (
              <p className="mt-1 text-sm" style={{ color: "var(--text-6)" }}>
                {subtitle}
              </p>
            )}
          </div>
        </div>

        <div
          className="rounded-2xl p-7"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(34px) saturate(190%)",
            WebkitBackdropFilter: "blur(34px) saturate(190%)",
            boxShadow: "inset 0 1px 0 var(--border-default)",
            border: "1px solid var(--border-default)",
          }}
        >
          {children}
        </div>

        {footer && <div className="mt-6 text-center text-sm">{footer}</div>}
      </div>
    </main>
  );
}
