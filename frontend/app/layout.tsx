import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Inter, Manrope } from "next/font/google";
import "./globals.css";
import { AppFrame } from "@/components/dashboard/AppFrame";
import { InlineScript } from "@/components/InlineScript";
import { themeInitScript } from "@/lib/theme";

// Inter: body text, labels, navigation, buttons and tables. (The variable keeps its old name so existing styles still resolve.)
const inter = Inter({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

// Manrope: headings and the big financial figures on the signed-in dashboard (see components/dashboard/typography.css).
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Metrion",
  description: "AI profit-optimization OS for Indian e-commerce sellers",
};

// Clerk's theme engine takes literal colors, so these mirror the tokens in globals.css
// (colorPrimary=--ov-brand, colorBackground=--ov-card, colorText=--ov-ink,
// colorTextSecondary=--ov-ink-3). Keep them in sync if those tokens change.
const clerkAppearance = {
  variables: {
    colorPrimary: "#fafafa",
    colorBackground: "#0e0e10",
    colorInputBackground: "#0f0f11",
    colorInputText: "#fafafa",
    colorText: "#fafafa",
    colorTextSecondary: "#a1a1aa",
    borderRadius: "14px",
    fontFamily: "Inter, sans-serif",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${manrope.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        <InlineScript html={themeInitScript} />
      </head>
      <body className="min-h-full flex flex-col" style={{ background: "var(--bg-base)" }}>
        {/* Metrion's backend creates the Clerk org during onboarding (auth.md §6.2), so if the
            Clerk instance leaves a new session "pending" on choose-organization, route it to
            our own onboarding step instead of Clerk's (unrendered) task UI. */}
        <ClerkProvider appearance={clerkAppearance} taskUrls={{ "choose-organization": "/onboarding" }}>
          <AppFrame>{children}</AppFrame>
        </ClerkProvider>
      </body>
    </html>
  );
}
