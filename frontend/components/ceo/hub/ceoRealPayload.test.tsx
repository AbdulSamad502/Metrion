import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";
import type { FindingRow, InvestigationDetail } from "@/lib/ceo";
import real from "@/test-support/fixtures/ceoRealTurn.json";

// The payloads here were produced by the real backend (backend/tests/integration/test_ceo_http_end_to_end.py captures them; that test fails if this file's structure
// stops matching the real response). Rendering them proves the Hub shows what the backend actually sends: the answer, each specialist's finding, the figures
// with their register, and an honest "not available" for what could not be computed. The conversation is reopened the way a refresh does it.
const detail = real.detail as unknown as InvestigationDetail;
const findings = detail.findings as FindingRow[];

let fake: FakeCeo;
beforeEach(() => {
  fake = new FakeCeo();
  fake.seed({ id: detail.investigation.id, investigation: detail.investigation, agents: detail.agents, messages: detail.messages, turns: detail.turns, findings });
  sessionStorage.setItem("metrion.ceoHub.openInvestigation", detail.investigation.id);
});

const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);

describe("a conversation with a real specialist, as the backend sent it", () => {
  it("restores the thread: the question and the CEO's answer exactly as stored, with no unrendered marker", async () => {
    mount();
    const conversation = await screen.findByTestId("conversation");
    expect(within(conversation).getByText(detail.messages[0].content)).toBeInTheDocument();
    expect(conversation).toHaveTextContent("₹482,150.00");
    expect(conversation.textContent).not.toContain("{{");
  });

  it("shows one card per finding, each from the agent that produced it", async () => {
    mount();
    await screen.findByTestId("conversation");
    for (const f of findings) expect(await screen.findByTestId(`finding-${f.id}`)).toHaveAttribute("data-status", f.status);
    const cfo = findings.filter((f) => f.source === "CFO");
    expect(cfo.map((f) => f.action_key).sort()).toEqual(["cfo.anomaly_check", "cfo.financial_health", "cfo.strategic_briefing"]);
  });

  it("shows each stored figure with its value and register, and the provenance it rests on", async () => {
    mount();
    await screen.findByTestId("conversation");
    const health = findings.find((f) => f.action_key === "cfo.financial_health") as FindingRow;
    const card = await screen.findByTestId(`finding-${health.id}`);
    for (const fig of health.presentation?.figures ?? []) {
      expect(card).toHaveTextContent(fig.value);
      expect(card).toHaveTextContent(fig.label);
    }
    expect(card).toHaveTextContent(`Provenance: ${health.figure_refs.length} verified`);
  });

  it("says a result that could not be computed is not available, and shows no number for it", async () => {
    mount();
    await screen.findByTestId("conversation");
    const leak = findings.find((f) => f.status === "UNAVAILABLE") as FindingRow;
    const card = await screen.findByTestId(`finding-${leak.id}`);
    expect(card).toHaveAttribute("data-status", "UNAVAILABLE");
    expect(card.textContent).not.toMatch(/₹\s?\d/);
  });

  it("asks the backend for the conversation once to restore it (no duplicate reads)", async () => {
    mount();
    await screen.findByTestId("conversation");
    expect(fake.count("getInvestigation")).toBe(1);
  });
});
