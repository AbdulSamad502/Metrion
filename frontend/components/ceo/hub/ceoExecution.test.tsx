import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ExecutionPanel, executionStatusOf } from "@/components/ceo/hub/ExecutionPanel";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

const IDLE = { phase: "idle" as const, question: null, arrivedIds: [], error: null, last: null, stage: null, working: [] };

describe("execution status comes only from reported state", () => {
  it("maps each real condition to one status; there is no planning or approval state", () => {
    const base = { state: "ACTIVE" as const, needsInput: false, lastTurnStatus: null, error: null };
    expect(executionStatusOf(base)).toBe("IDLE");
    expect(executionStatusOf({ ...base, state: "PROCESSING" })).toBe("RUNNING");
    expect(executionStatusOf({ ...base, needsInput: true })).toBe("AWAITING_INPUT");
    expect(executionStatusOf({ ...base, lastTurnStatus: "DELIVERED" })).toBe("COMPLETED");
    expect(executionStatusOf({ ...base, lastTurnStatus: "FAILED" })).toBe("FAILED");
    expect(executionStatusOf({ ...base, lastTurnStatus: "DENIED" })).toBe("DENIED");
    expect(executionStatusOf({ ...base, state: "RESOLVED", lastTurnStatus: "DELIVERED" })).toBe("CLOSED");
  });

  it("says nothing has run instead of showing activity when there are no turns", () => {
    render(<ExecutionPanel state="NEW" needsInput={false} turn={IDLE} turns={[]} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "IDLE");
    expect(screen.getByTestId("execution-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("execution-running")).toBeNull();
  });

  it("shows the live stage and the specialists running, with real turn history and timestamps", () => {
    const turns = [{ id: "t1", route: "SPECIALIST", route_key: "cfo.pricing", status: "DELIVERED", composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-09T10:00:00Z" }];
    render(<ExecutionPanel state="PROCESSING" needsInput={false} turn={{ ...IDLE, phase: "processing", stage: "Checking your costs", question: "Is my margin ok?" }} turns={turns as never} working={[{ code: "CFO", label: "Working · margin check" }]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "RUNNING");
    expect(screen.getByText("Checking your costs")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Agents working now")).getByText(/margin check/)).toBeInTheDocument();
    expect(within(screen.getByTestId("execution-history")).getByText("Completed")).toBeInTheDocument();
  });
});

describe("approval refusal", () => {
  it("shows 'Needs an approved plan' for a turn refused for approval, and 'Not allowed' for an ordinary denial", () => {
    const mk = (cr: unknown) => [{ id: "t1", route: "ADVISORY", route_key: null, status: "DENIED", composition_mode: null, user_message_id: "m1", ceo_message_id: null, created_at: "2026-10-11T10:00:00Z", classifier_result: cr }];
    const { unmount } = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={mk({ approvalRequiredFor: "cmo.market_trends" }) as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "APPROVAL_REQUIRED");
    expect(screen.getAllByText("Needs an approved plan").length).toBeGreaterThan(0);
    expect(screen.getByText(/approval is not available yet/)).toBeInTheDocument();
    unmount();
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={mk(null) as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "DENIED");
    expect(screen.queryByText("Needs an approved plan")).toBeNull();
  });

  const row = (over: Record<string, unknown>) => ({ id: "t1", route: "ADVISORY", route_key: null, status: "DENIED", composition_mode: null, user_message_id: "m1", ceo_message_id: null, created_at: "2026-10-11T10:00:00Z", ...over });
  it("labels the task row and the status for an approval refusal, and 'Not allowed' for an ordinary denial", () => {
    const a = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={[row({ classifier_result: { approvalRequiredFor: "pi.discover" } })] as never} working={[]} />);
    expect(within(screen.getByTestId("execution-history")).getByText("Needs an approved plan")).toBeInTheDocument();
    a.unmount();
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={[row({})] as never} working={[]} />);
    expect(within(screen.getByTestId("execution-history")).getByText("Not allowed")).toBeInTheDocument();
    expect(screen.queryByText("Needs an approved plan")).toBeNull();
  });

  it("ignores approval-related wording elsewhere and non-denied turns", () => {
    const { unmount } = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={{ ...IDLE, error: "Approval required: needs an approved plan" }} turns={[row({ classifier_result: { reason: "approval required" } })] as never} working={[]} />);
    expect(screen.queryByText("Needs an approved plan")).toBeNull();
    expect(screen.getByTestId("execution-panel")).not.toHaveAttribute("data-status", "APPROVAL_REQUIRED");
    unmount();
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={[row({ status: "DELIVERED", outcome: "SUCCEEDED", classifier_result: { approvalRequiredFor: "pi.discover" } })] as never} working={[]} />);
    expect(screen.queryByText("Needs an approved plan")).toBeNull();
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "COMPLETED");
  });

  it("does not crash with no turns or a null classifier record", () => {
    const { unmount } = render(<ExecutionPanel state="NEW" needsInput={false} turn={IDLE} turns={[]} working={[]} />);
    expect(screen.getByTestId("execution-empty")).toBeInTheDocument();
    unmount();
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={[row({ classifier_result: null }), row({ id: "t2", classifier_result: undefined })] as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "DENIED");
  });
});

describe("hub layout", () => {
  let fake: FakeCeo;
  beforeEach(() => { fake = new FakeCeo(); });
  it("shows one full-width view at a time (agents, conversation, activity and results), all mounted, with the chat bar always below them", async () => {
    render(<CeoHubWorkspace client={fake.client()} feedFactory={new ManualFeed().factory} />);
    const chat = await screen.findByTestId("chat-column");
    const bar = screen.getByTestId("chat-bar");
    expect(within(bar).getByTestId("composer")).toBeInTheDocument();
    expect(within(chat).queryByTestId("composer")).toBeNull(); // the chat bar is outside every view
    const canvasArea = screen.getByTestId("work-area");
    expect(within(canvasArea).getByTestId("agent-canvas")).toBeInTheDocument(); // the agents view is mounted even while another view is open
    expect(screen.getByTestId("right-tab-chat")).toHaveAttribute("aria-selected", "true");
    expect(chat).not.toHaveClass("hidden");
    expect(canvasArea).toHaveClass("hidden");
    await userEvent.setup().click(screen.getByTestId("right-tab-results"));
    expect(screen.getByTestId("right-tab-results")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("results-area")).not.toHaveClass("hidden");
    expect(chat).toHaveClass("hidden");
    await userEvent.setup().click(screen.getByTestId("tab-agents"));
    expect(canvasArea).not.toHaveClass("hidden");
    expect(screen.getByTestId("composer")).toBeInTheDocument(); // still there
  });
});

describe("the PLANNED turn status (vocabulary only)", () => {
  it("is shown neutrally, never as a failure, and does not change the task status", () => {
    const turns = [{ id: "t1", route: "ACTION", route_key: "cfo.reconcile", status: "PLANNED", composition_mode: null, user_message_id: "m1", ceo_message_id: null, created_at: "2026-10-11T10:00:00Z" }];
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={turns as never} working={[]} />);
    expect(within(screen.getByTestId("execution-history")).getByText("Planned")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).toBeNull();
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "IDLE");
  });
});

describe("a delivered turn is not automatically a success (stored outcome)", () => {
  const delivered = (outcome: string | null) => [{ id: "t1", route: "PLAYBOOK", route_key: "PROFIT_DIAGNOSIS", status: "DELIVERED", outcome, composition_mode: null, user_message_id: "m1", ceo_message_id: "m2", created_at: "2026-10-11T10:00:00Z" }];
  it("shows a failed required step as a failure even though the answer was delivered", () => {
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered("FAILED") as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "FAILED");
    expect(within(screen.getByTestId("execution-history")).getByText("Could not complete")).toBeInTheDocument();
  });
  it("shows partial and pending-input outcomes plainly, and an explained out-of-scope reply neutrally", () => {
    const { unmount } = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered("PARTIAL") as never} working={[]} />);
    expect(within(screen.getByTestId("execution-history")).getByText("Partly completed")).toBeInTheDocument();
    unmount();
    const second = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered("PENDING_INPUT") as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "AWAITING_INPUT");
    second.unmount();
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered("DECLINED") as never} working={[]} />);
    expect(within(screen.getByTestId("execution-history")).getByText("Explained")).toBeInTheDocument();
  });
  it("headlines a partly completed task as partial, never as plain completed, and says what that means", () => {
    expect(executionStatusOf({ state: "ACTIVE", needsInput: false, lastTurnStatus: "DELIVERED", lastTurnOutcome: "PARTIAL", error: null })).toBe("PARTIAL");
    expect(executionStatusOf({ state: "ACTIVE", needsInput: false, lastTurnStatus: "DELIVERED", lastTurnOutcome: "SUCCEEDED", error: null })).toBe("COMPLETED");
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered("PARTIAL") as never} working={[]} />);
    const panel = screen.getByTestId("execution-panel");
    expect(panel).toHaveAttribute("data-status", "PARTIAL");
    expect(within(panel).getAllByText("Partly completed").length).toBeGreaterThanOrEqual(2); // the headline and the history row agree
    expect(within(panel).queryByText("Completed")).toBeNull();
    expect(screen.getByTestId("execution-partial")).toHaveTextContent("Some steps finished and some did not");
  });
  it("shows an unfinished turn as in progress, never as a raw status code", () => {
    for (const status of ["RECEIVED", "CAP_CHECKED", "CLASSIFIED", "PLAN_VALIDATED", "DISPATCHED", "GATHERED", "COMPOSED"]) {
      const turns = [{ id: "t1", route: "ADVISORY", route_key: null, status, outcome: null, composition_mode: null, user_message_id: "m1", ceo_message_id: null, created_at: "2026-10-12T10:00:00Z" }];
      const { unmount } = render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={turns as never} working={[]} />);
      expect(within(screen.getByTestId("execution-history")).getByText("In progress")).toBeInTheDocument();
      expect(screen.queryByText(/plan validated|dispatched|cap checked/i)).toBeNull();
      unmount();
    }
  });
  it("leaves a legacy turn (no outcome) exactly as before", () => {
    render(<ExecutionPanel state="ACTIVE" needsInput={false} turn={IDLE} turns={delivered(null) as never} working={[]} />);
    expect(screen.getByTestId("execution-panel")).toHaveAttribute("data-status", "COMPLETED");
  });
});
