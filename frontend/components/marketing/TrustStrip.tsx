const MARKETPLACES = ["Amazon", "Flipkart", "Meesho"];

export function TrustStrip() {
  return (
    <div className="mx-auto mt-9 max-w-[1280px] px-6 pt-6" style={{ borderTop: "1px solid var(--border-subtle)" }}>
      <div className="mb-4 text-center font-mono text-[11px] tracking-[0.06em]" style={{ color: "var(--text-8)" }}>
        BUILT FOR SELLERS ON
      </div>
      <div className="flex flex-wrap items-center justify-center gap-10 sm:gap-16">
        {MARKETPLACES.map((name) => (
          <span key={name} className="text-[20px] font-bold whitespace-nowrap sm:text-[22px]" style={{ color: "var(--text-4)" }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
