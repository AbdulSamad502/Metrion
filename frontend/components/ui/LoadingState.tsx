/** Skeleton placeholder while data loads — shape-matched, announced once to assistive tech. */
export function LoadingState({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="flex flex-col gap-2.5">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="mt-skeleton h-3.5" style={{ width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span className="mt-spinner inline-block" style={{ width: size, height: size }} aria-hidden />;
}
