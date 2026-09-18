import { About } from "@/components/marketing/About";
import { AgentFlow } from "@/components/marketing/AgentFlow";
import { Features } from "@/components/marketing/Features";
import { FinalCta } from "@/components/marketing/FinalCta";
import { Footer } from "@/components/marketing/Footer";
import { Hero } from "@/components/marketing/Hero";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { LandingGate } from "@/components/marketing/LandingGate";
import { LandingNav } from "@/components/marketing/LandingNav";
import { Pricing } from "@/components/marketing/Pricing";
import { StatsStrip } from "@/components/marketing/StatsStrip";
import { TrustStrip } from "@/components/marketing/TrustStrip";
import { WhyMetrion } from "@/components/marketing/WhyMetrion";

/** Metrion's public marketing landing page — everything a signed-out visitor sees before
 * authentication. Lives at the app root (outside the `(marketing)` route group) so it gets
 * its own full nav instead of the minimal header shared by the sign-in/up/forgot-password/
 * onboarding screens. `LandingGate` sends anyone already signed in straight to /dashboard
 * rather than showing them the pitch again. */
export default function Home() {
  return (
    <LandingGate>
      <LandingNav />
      <main className="flex-1">
        <Hero />
        <TrustStrip />
        <Features />
        <StatsStrip />
        <HowItWorks />
        <AgentFlow />
        <WhyMetrion />
        <Pricing />
        <About />
        <FinalCta />
      </main>
      <Footer />
    </LandingGate>
  );
}
