import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";
import type { SharedFinding } from "@/lib/ceo";

// Spec agent-needs-and-shared-knowledge.md 6.3 / 6.5: what the agents reported, with fixed trust wording, never shown as verified unless it is, and forgettable.
let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
const finding = (over: Partial<SharedFinding> = {}): SharedFinding => ({
  id: "f1", agent: "PI", kind: "PRODUCT_IDEA", subject: "Steel water bottle", text: "Product Intelligence listed this idea in its latest research.", trust: "AGENT_REPORTED",
  trustLabel: "Reported by Product Intelligence, not verified", figureRefs: [], sourceRef: { kind: "run", id: "r1" }, createdAt: "2026-10-10T10:00:00Z", ...over,
});

describe("what the agents have reported", () => {
  it("says plainly when nothing has been reported yet", async () => {
    mount();
    await waitFor(() => expect(fake.count("getSharedFindings")).toBe(1));
    expect(screen.queryByTestId("shared-findings-panel")).not.toBeInTheDocument(); // nothing reported: no empty panel
    expect(fake.count("getSharedFindings")).toBe(1);
  });

  it("shows each finding with the backend's own trust wording, and never words an unchecked one as verified", async () => {
    fake.shared = [
      finding(),
      finding({ id: "f2", agent: "CFO", kind: "FIGURE", subject: null, text: "Contribution profit was saved for September.", trust: "ENGINE_VERIFIED", trustLabel: "Calculated by the engine", figureRefs: [{ kind: "ENGINE_RESULT", id: "e1", label: "Contribution profit", resolvable: true }, { kind: "ENGINE_RESULT", id: "e2", resolvable: false }] }),
    ];
    mount();
    const reported = await screen.findByTestId("shared-finding-f1");
    expect(within(reported).getByText("Reported by Product Intelligence, not verified")).toBeInTheDocument();
    expect(within(reported).getByText("“Steel water bottle”")).toBeInTheDocument();
    expect(reported).not.toHaveTextContent("Calculated by the engine");
    const verified = screen.getByTestId("shared-finding-f2");
    expect(within(verified).getByText("Calculated by the engine")).toBeInTheDocument();
    expect(verified).toHaveTextContent("2 cited figures");
    expect(verified).toHaveTextContent("1 no longer traceable");
  });

  it("shows entries from agents the member cannot use only as a count", async () => {
    fake.hiddenFindings = [{ agent: "CFO", count: 2, message: "2 findings from CFO not shown: no access" }];
    mount();
    expect(await screen.findByTestId("shared-findings-hidden")).toHaveTextContent("2 findings from CFO not shown: no access");
  });

  it("asks before forgetting, forgets only on confirmation, and then refreshes the list from the server", async () => {
    fake.shared = [finding()];
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: /Forget: Steel water bottle/ }));
    expect(fake.count("forgetSharedFinding")).toBe(0); // nothing is forgotten by the first click
    await u.click(screen.getByRole("button", { name: "Keep" }));
    expect(fake.count("forgetSharedFinding")).toBe(0);
    await u.click(screen.getByRole("button", { name: /Forget: Steel water bottle/ }));
    await u.click(within(screen.getByRole("group", { name: "Confirm forgetting" })).getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(fake.count("forgetSharedFinding")).toBe(1));
    expect(fake.calls.find((c) => c.method === "forgetSharedFinding")?.args).toEqual(["f1"]);
    await waitFor(() => expect(screen.queryByTestId("shared-finding-f1")).not.toBeInTheDocument());
    expect(fake.count("getSharedFindings")).toBeGreaterThanOrEqual(2); // re-read after the action, not assumed
  });

  it("says so, and offers a retry, when the list cannot be loaded; it does not claim there is nothing", async () => {
    fake.sharedError = new ApiError(500, { detail: "boom" });
    mount();
    expect(await screen.findByTestId("shared-findings-error")).toBeInTheDocument();
    expect(screen.queryByTestId("shared-findings-empty")).not.toBeInTheDocument();
    fake.sharedError = null;
    fake.shared = [finding()];
    await userEvent.setup().click(within(screen.getByTestId("shared-findings-panel")).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("shared-finding-f1")).toBeInTheDocument();
  });
});
