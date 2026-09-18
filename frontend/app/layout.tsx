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
      <body className="min-h-full flex flex-col" style={{ background: "#0A0B0A" }}>
        <ClerkProvider appearance={clerkAppearance}>{children}</ClerkProvider>
      </body>
    </html>
  );
}
