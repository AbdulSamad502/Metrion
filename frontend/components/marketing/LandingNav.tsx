"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

const LINKS = [
  { href: "#home", label: "Home" },
  { href: "#features", label: "Features" },
  { href: "#why-metrion", label: "Why Metrion" },
  { href: "#pricing", label: "Pricing" },
  { href: "#about", label: "About" },
];

function scrollToSection(e: React.MouseEvent<HTMLAnchorElement>, href: string) {
  const target = document.querySelector(href);
  if (!target) return;
  e.preventDefault();
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [activeHref, setActiveHref] = useState("#home");

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sections = LINKS.map((l) => document.querySelector(l.href)).filter((el): el is Element => !!el);
    if (!sections.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveHref(`#${entry.target.id}`);
        }
      },
      { rootMargin: "-40% 0px -50% 0px" },
    );
    sections.forEach((s) => observer.observe(s));
    return () => observer.disconnect();
  }, []);

  return (
    <header
      className="sticky top-0 z-50 transition-colors duration-300"
      style={{
        background: scrolled ? "rgba(10, 11, 10, 0.72)" : "transparent",
        backdropFilter: scrolled ? "blur(20px) saturate(160%)" : "none",
        borderBottom: `1px solid ${scrolled ? "var(--border-subtle)" : "transparent"}`,
      }}
    >
      <div className="mx-auto flex h-[72px] max-w-[1280px] items-center justify-between px-6 sm:px-10">
        <Link href="/" className="flex items-center gap-2.5" style={{ animation: "mt-logo-intro 1s cubic-bezier(.16,1,.3,1) 0.1s both" }}>
          <Image src="/metrion-mark.png" alt="" width={30} height={30} priority />
          <span className="text-[17px] font-bold" style={{ color: "var(--text-1)" }}>
            Metrion
          </span>
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {LINKS.map((l) => {
            const active = activeHref === l.href;
            return (
              <a
                key={l.href}
                href={l.href}
                onClick={(e) => scrollToSection(e, l.href)}
                className="relative pb-1 text-[13.5px] font-medium transition-colors hover:text-white"
                style={{ color: active ? "var(--text-1)" : "var(--text-4)" }}
              >
                {l.label}
                {active && (
                  <span
                    className="absolute -bottom-0.5 left-0 h-[2px] w-full rounded-full"
                    style={{ background: "var(--accent)" }}
                  />
                )}
              </a>
            );
          })}
        </nav>

        <div className="hidden items-center gap-4 md:flex">
          <Link href="/sign-in" className="text-[13.5px] font-semibold transition-colors hover:text-white" style={{ color: "var(--text-4)" }}>
            Sign in
          </Link>
          <Link
            href="/sign-up"
            className="rounded-lg px-4 py-2.5 text-[13.5px] font-bold transition-all hover:brightness-110 active:scale-[0.97]"
            style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
          >
            Get started
          </Link>
        </div>

        <button
          type="button"
          aria-label="Toggle menu"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen((v) => !v)}
          className="flex h-9 w-9 items-center justify-center rounded-lg md:hidden"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-2)" }}
        >
          {mobileOpen ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M2 2L14 14M14 2L2 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
              <path d="M2 4H14M2 8H14M2 12H14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          )}
        </button>
      </div>

      {mobileOpen && (
        <div
          className="flex flex-col gap-1 px-6 pb-5 md:hidden"
          style={{ borderTop: "1px solid var(--border-subtle)", background: "rgba(10, 11, 10, 0.96)" }}
        >
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              onClick={(e) => {
                scrollToSection(e, l.href);
                setMobileOpen(false);
              }}
              className="rounded-lg px-2 py-3 text-sm font-medium"
              style={{ color: "var(--text-3)" }}
            >
              {l.label}
            </a>
          ))}
          <div className="mt-2 flex flex-col gap-2 border-t pt-4" style={{ borderColor: "var(--border-subtle)" }}>
            <Link
              href="/sign-in"
              className="rounded-lg px-4 py-3 text-center text-sm font-semibold"
              style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className="rounded-lg px-4 py-3 text-center text-sm font-bold"
              style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
            >
              Get started
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
