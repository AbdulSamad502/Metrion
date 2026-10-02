import type { ReactNode } from "react";

/** The workspace's standard block: a heading with a hairline rule, then content on a borderless
 * panel. Replaces "every block is an outlined card" — the rule does the separating, so a page of
 * ten sections reads as a document, not ten boxes. Pass `panel={false}` for content that already
 * carries its own structure (tables, ledgers, lists). */
export function Section({
  title,
  hint,
  action,
  panel = true,
  children,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
  panel?: boolean;
  children: ReactNode;
}) {
  return (
    <section>
      <header className="mt-section__head">
        <div className="min-w-0">
          <h2 className="mt-section__title">{title}</h2>
          {hint && <p className="mt-section__hint">{hint}</p>}
        </div>
        {action && <div className="flex flex-shrink-0 items-center gap-3">{action}</div>}
      </header>
      <div className={panel ? "mt-panel" : undefined}>{children}</div>
    </section>
  );
}
