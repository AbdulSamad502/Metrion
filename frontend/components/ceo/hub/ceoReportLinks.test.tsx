import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { findingLink } from "@/lib/ceoModel";
import type { CeoMessage, Presentation } from "@/lib/ceo";
import { FakeCeo, ManualFeed, finding } from "@/test-support/fakeCeo";

// The full analysis behind an answer lives in the owning agent's own page; the Hub gives a real button to it (owner's first live run, 2026-10-10).
const RUN = "11111111-2222-3333-4444-555555555555";
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const pres: Presentation = { version: 1, headline: "Product ideas found on the public web ready", figures: [], facts: [], gaps: [], offers: [], artefacts: [{ title: "Product ideas found on the public web", items: ["Nike SB Shoes"], note: null }] };
const msg = (over: Partial<CeoMessage> & Pick<CeoMessage, "role" | "content">): CeoMessage => ({ id: `m-${Math.random().toString(36).slice(2)}`, kind: over.role === "USER" ? "TEXT" : "ANSWER", turn_id: null, created_at: "2026-10-10T09:00:00.000Z", ...over });

describe("the link to the full analysis", () => {
  it("opens the exact research run for Product Intelligence and the agent's page for the others, and never for a refused finding", () => {
    expect(findingLink({ source: "PI", action_key: "pi.report", status: "COMPLETE", report_ref: { runId: RUN } })).toEqual({ href: `/dashboard/pi?run=${RUN}`, label: "View Detailed Research" });
    expect(findingLink({ source: "PI", action_key: "pi.report", status: "COMPLETE", report_ref: null })?.href).toBe("/dashboard/pi");
    expect(findingLink({ source: "CFO", action_key: "cfo.financial_health", status: "PARTIAL", report_ref: null })?.href).toBe("/dashboard/cfo");
    expect(findingLink({ source: "CI", action_key: "x", status: "COMPLETE", report_ref: null })?.href).toBe("/dashboard/competitors");
    expect(findingLink({ source: "CMO", action_key: "x", status: "COMPLETE", report_ref: null })?.href).toBe("/dashboard/cmo");
    expect(findingLink({ source: "PI", action_key: "pi.report", status: "DENIED", report_ref: { runId: RUN } })).toBeNull();
    expect(findingLink({ source: "BUSINESS_STATE", action_key: "BS_PNL_LATEST", status: "COMPLETE", report_ref: null })).toBeNull();
  });

  it("puts a button under the CEO's answer that opens the research report", async () => {
    const id = fake.seed({
      id: "inv-1", messages: [msg({ role: "USER", content: "find trending products" }), msg({ id: "a1", role: "CEO", content: "Here is what Product Intelligence found.", turn_id: "t1" })],
      findings: [finding({ id: "fp", turn_id: "t1", source: "PI", action_key: "pi.report", status: "COMPLETE", report_ref: { runId: RUN }, presentation: pres })],
    });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const u = userEvent.setup();
    if (!screen.queryByTestId("drawer")) await u.click(await screen.findByTestId("open-drawer"));
    await u.click(await screen.findByTestId(`investigation-${id}`));
    const bar = await screen.findByTestId("report-buttons");
    const link = within(bar).getByTestId("report-button");
    expect(link).toHaveTextContent("View Detailed Research");
    expect(link).toHaveAttribute("href", `/dashboard/pi?run=${RUN}`);
  });
});
