import Image from "next/image";
import Link from "next/link";

const COLUMNS: { title: string; links: { label: string; href: string }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Features", href: "#features" },
      { label: "How it works", href: "#how-it-works" },
      { label: "Why Metrion", href: "#why-metrion" },
      { label: "Pricing", href: "#pricing" },
    ],
  },
  {
    title: "Agents",
    links: [
      { label: "Product Intelligence", href: "#features" },
      { label: "Competitor Intelligence", href: "#features" },
      { label: "Full CFO", href: "#features" },
      { label: "Slim CMO", href: "#features" },
    ],
  },
  {
    title: "Account",
    links: [
      { label: "About", href: "#about" },
      { label: "Sign in", href: "/sign-in" },
      { label: "Get started", href: "/sign-up" },
    ],
  },
];

export function Footer() {
  return (
    <footer style={{ borderTop: "1px solid var(--border-subtle)" }}>
      <div className="mx-auto grid max-w-[1280px] grid-cols-2 gap-8 px-6 py-14 sm:grid-cols-[1.4fr_repeat(3,1fr)] sm:px-10">
        <div className="col-span-2 flex flex-col gap-3 sm:col-span-1">
          <Image src="/metrion-mark.png" alt="Metrion" width={30} height={30} />
          <p className="max-w-[220px] text-[12.5px] leading-relaxed" style={{ color: "var(--text-7)" }}>
            The profit-optimization OS for Indian e-commerce sellers.
          </p>
        </div>
        {COLUMNS.map((col) => (
          <div key={col.title} className="flex flex-col gap-3">
            <div className="text-[13px] font-bold" style={{ color: "var(--text-2)" }}>
              {col.title}
            </div>
            {col.links.map((l) => (
              <Link key={l.label} href={l.href} className="text-[13px] font-medium transition-colors hover:text-white" style={{ color: "var(--text-6)" }}>
                {l.label}
              </Link>
            ))}
          </div>
        ))}
      </div>
      <div className="mx-auto max-w-[1280px] px-6 pb-8 sm:px-10">
        <div className="text-[12px]" style={{ color: "var(--text-8)" }}>
          © {new Date().getFullYear()} Metrion. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
