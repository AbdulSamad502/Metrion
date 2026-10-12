import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { RecentDecisions } from "@/components/ceo/hub/RecentDecisions";
import type { InvestigationSummary } from "@/lib/ceo";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

const inv = (over: Partial<InvestigationSummary> & Pick<InvestigationSummary, "id">): InvestigationSummary => ({
  title: "A conversation", status: "ACTIVE", origin: "USER_CHAT", created_at: "2026-10-01T00:00:00Z", last_message_at: "2026-10-01T00:00:00Z", ...over,
});

describe("RecentDecisions shows only what the seller actually resolved", () => {
  it("says so plainly when nothing is resolved, and never invents a decision", () => {
    render(<RecentDecisions status="ready" items={[inv({ id: "a" }), inv({ id: "b", status: "ARCHIVED" })]} onOpen={() => undefined} />);
    expect(screen.getByText(/No recent decisions yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lists the three newest resolved conversations, newest first, and opens one", async () => {
    const opened: string[] = [];
    const items = [
      inv({ id: "old", title: "Oldest", status: "RESOLVED", last_message_at: "2026-09-01T00:00:00Z" }),
      inv({ id: "new", title: "Newest", status: "RESOLVED", last_message_at: "2026-10-09T00:00:00Z" }),
      inv({ id: "mid", title: "Middle", status: "RESOLVED", last_message_at: "2026-09-20T00:00:00Z" }),
      inv({ id: "ancient", title: "Ancient", status: "RESOLVED", last_message_at: "2026-01-01T00:00:00Z" }),
      inv({ id: "open", title: "Still open", status: "ACTIVE", last_message_at: "2026-10-10T00:00:00Z" }),
    ];
    render(<RecentDecisions status="ready" items={items} onOpen={(id) => opened.push(id)} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => within(b).getByText(/Newest|Middle|Oldest|Ancient|Still open/).textContent)).toEqual(["Newest", "Middle", "Oldest"]);
    await userEvent.setup().click(buttons[0]);
    expect(opened).toEqual(["new"]);
  });

  it("is honest while loading and when the list could not load", () => {
    const { rerender } = render(<RecentDecisions status="loading" items={[]} onOpen={() => undefined} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    rerender(<RecentDecisions status="error" items={[]} onOpen={() => undefined} />);
    expect(screen.getByText(/Could not load your conversations/)).toBeInTheDocument();
    expect(screen.queryByText(/No recent decisions yet/)).not.toBeInTheDocument(); // a failed load is not "no decisions"
  });
});

describe("the redesigned hub", () => {
  it("describes each specialist's role once, from fixed role text, and explains the canvas with real states only", async () => {
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const canvas = await screen.findByTestId("agent-canvas");
    expect(within(canvas).getByText("Discover & research")).toBeInTheDocument();
    expect(within(canvas).getByText("Financials & P&L")).toBeInTheDocument();
    expect(within(canvas).getByText("Competitors & market")).toBeInTheDocument();
    expect(within(canvas).getByText("Listings & marketing")).toBeInTheDocument();
    const legend = within(canvas).getByTestId("canvas-legend");
    expect(legend).toHaveTextContent(/Connected/);
    expect(legend).toHaveTextContent(/Removed/);
    expect(legend).toHaveTextContent(/Checking/);
    expect(legend.textContent).not.toMatch(/data flow|agent flow/i); // the canvas draws no data flow, so its legend must not promise one
  });

  it("shows the health and decisions cards with no invented score or sample recommendations", async () => {
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    await screen.findByTestId("agent-canvas");
    expect(screen.queryByTestId("summary-cards")).not.toBeInTheDocument(); // nothing real to summarise yet: no empty cards
    expect(screen.queryByText(/\b\d{1,3} ?\/ ?100\b/)).not.toBeInTheDocument(); // no "82 / 100" style score
    expect(screen.queryByText(/Upgrade to Pro/i)).not.toBeInTheDocument();
  });

  it("opens a resolved conversation from the decisions card", async () => {
    fake.seed({ id: "done", title: "Pricing call", status: "RESOLVED" });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    await userEvent.setup().click(await screen.findByRole("button", { name: /Pricing call/ }));
    expect(await screen.findByTestId("conversation")).toBeInTheDocument();
  });
});

describe("the message list is accessible", () => {
  it("is keyboard-reachable (it scrolls) and holds only list items", async () => {
    fake.seed({ id: "chat", messages: [{ id: "m1", role: "USER", kind: "TEXT", content: "hello", turn_id: null, created_at: "2026-10-08T09:00:00.000Z" }] });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const u = userEvent.setup();
    await u.click(await screen.findByTestId("open-drawer"));
    await u.click(await screen.findByTestId("investigation-chat"));
    const list = await screen.findByRole("list", { name: "Conversation" });
    expect(list).toHaveAttribute("tabindex", "0"); // axe: scrollable-region-focusable
    expect([...list.children].every((c) => c.tagName === "LI")).toBe(true); // axe: list
  });
});

describe("the Conversations dialog keeps its modal promises", () => {
  it("moves focus in, keeps Tab and Shift+Tab inside, closes on Escape and returns focus to the opener", async () => {
    fake.seed({ id: "one", title: "First" });
    fake.seed({ id: "two", title: "Second" });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const user = userEvent.setup();
    const opener = await screen.findByTestId("open-drawer");
    opener.focus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "Conversations and business overview" });
    expect(dialog.contains(document.activeElement)).toBe(true); // before: focus stayed on the button behind the dialog

    for (let i = 0; i < 20; i++) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true); // before: Tab reached the page behind (the composer)
    }
    for (let i = 0; i < 6; i++) {
      await user.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }

    await user.keyboard("{Escape}"); // before: nothing happened
    expect(screen.queryByTestId("drawer")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});

describe("each specialist on the canvas links to its real workspace", () => {
  it("offers the workspace by the same name the menu uses, and not for a locked specialist", async () => {
    fake.availability = { ...fake.availability, CMO: { status: "NOT_ENTITLED", chatActions: 0 } };
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    const finance = await screen.findByTestId("workspace-CFO");
    expect(finance).toHaveAttribute("href", "/dashboard/cfo");
    expect(finance).toHaveTextContent("Open Profit & Finance");
    expect(screen.getByTestId("workspace-CI")).toHaveAttribute("href", "/dashboard/competitors");
    expect(screen.getByTestId("workspace-PI")).toHaveAttribute("href", "/dashboard/pi");
    expect(screen.queryByTestId("workspace-CMO")).not.toBeInTheDocument(); // not on the plan: no link to a page it cannot use
  });
});
