/** Inline, recoverable error — plain words from the API, with an optional retry. */
export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-xl px-3.5 py-2.5 t-body-sm"
      style={{ background: "var(--negative-fill)", color: "var(--negative)" }}
    >
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-btn rounded-lg px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--negative)" }}>
          Retry
        </button>
      )}
    </div>
  );
}
