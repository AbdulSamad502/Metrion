export function Topbar({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div
      className="sticky top-0 z-10 flex flex-shrink-0 items-center justify-between gap-5 px-8 py-5"
      style={{
        background: "var(--bg-header)",
        backdropFilter: "blur(34px) saturate(195%)",
        borderBottom: "1px solid var(--border-subtle)",
      }}
    >
      <div className="min-w-0">
        <div className="text-2xl font-bold" style={{ color: "var(--text-1)" }}>
          {title}
        </div>
        <div className="mt-0.5 text-[13px]" style={{ color: "var(--text-5)" }}>
          {subtitle}
        </div>
      </div>
      <div className="flex flex-shrink-0 items-center gap-2.5">
        <div
          className="flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-2 text-xs"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-4)" }}
        >
          <span>May 10 – May 16, 2025</span>
        </div>
        <button
          type="button"
          className="flex h-8.5 w-8.5 items-center justify-center rounded-xl"
          style={{ border: "1px solid var(--border-default)" }}
          aria-label="Notifications"
        >
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="var(--text-4)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 2.5C7 2.5 5.5 4.8 5.5 8V11L4 13.5H16L14.5 11V8C14.5 4.8 13 2.5 10 2.5Z" />
            <path d="M8.2 15.5C8.2 16.6 9 17.5 10 17.5C11 17.5 11.8 16.6 11.8 15.5" />
          </svg>
        </button>
        <button
          type="button"
          className="whitespace-nowrap rounded-xl px-3.5 py-2 text-xs font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          Ask Metrion
        </button>
      </div>
    </div>
  );
}
