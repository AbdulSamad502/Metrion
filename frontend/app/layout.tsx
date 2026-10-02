import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Metrion",
  description: "AI profit-optimization OS for Indian e-commerce sellers",
};

// Clerk's theme engine takes literal colors, so these mirror the tokens in globals.css
// (colorPrimary=--accent, colorBackground=--bg-popover, colorText=--text-2,
// colorTextSecondary=--text-5). Keep them in sync if those tokens change.
const clerkAppearance = {
  variables: {
    colorPrimary: "#3ECF74",
    colorBackground: "#14150F",
    colorInputBackground: "rgba(18, 20, 17, 0.5)",
    colorInputText: "#F2F4F0",
    colorText: "#F2F4F0",
    colorTextSecondary: "#8A9188",
    borderRadius: "14px",
    fontFamily: "Inter, sans-serif",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col" style={{ background: "var(--bg-base)" }}>
        {/* Metrion's backend creates the Clerk org during onboarding (auth.md §6.2), so if the
            Clerk instance leaves a new session "pending" on choose-organization, route it to
            our own onboarding step instead of Clerk's (unrendered) task UI. */}
        <ClerkProvider appearance={clerkAppearance} taskUrls={{ "choose-organization": "/onboarding" }}>{children}</ClerkProvider>
      </body>
    </html>
  );
}
