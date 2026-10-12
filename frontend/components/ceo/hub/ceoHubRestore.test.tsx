import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});
afterEach(() => vi.restoreAllMocks());

const mount = () => render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);

async function open(id: string) {
  const u = userEvent.setup();
  if (!screen.queryByTestId("drawer")) await u.click(await screen.findByTestId("open-drawer"));
  await u.click(await screen.findByTestId(`investigation-${id}`));
  await screen.findByTestId("conversation");
}

describe("the open conversation survives a refresh", () => {
  it("reopens the conversation that was open, from the seller's own list, without a click", async () => {
    fake.seed({ id: "inv-1", title: "Why did profit drop?" });
    const first = mount();
    await open("inv-1");
    first.unmount(); // a refresh: a new mount, the same browser tab

    mount();
    expect(await screen.findByTestId("conversation")).toBeInTheDocument();
    expect(fake.count("getInvestigation")).toBe(2); // once per mount: the restored one is a normal, real load
  });

  it("falls back to the welcome screen and forgets an id that is no longer in the list", async () => {
    sessionStorage.setItem("metrion.ceoHub.openInvestigation", "someone-elses-or-deleted");
    fake.seed({ id: "inv-1" });
    mount();
    await screen.findByTestId("welcome");
    await waitFor(() => expect(sessionStorage.getItem("metrion.ceoHub.openInvestigation")).toBeNull());
    expect(fake.count("getInvestigation")).toBe(0); // never requested: only ids from the seller's own list are reopened
  });

  it("works exactly as before when browser storage is unavailable", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fake.seed({ id: "inv-1" });
    mount();
    await screen.findByTestId("welcome");
    await open("inv-1"); // selecting still works; nothing throws
    expect(screen.getByTestId("conversation")).toBeInTheDocument();
  });

  it("does not override a conversation the seller opened before the list arrived", async () => {
    sessionStorage.setItem("metrion.ceoHub.openInvestigation", "inv-1");
    fake.seed({ id: "inv-1" });
    fake.seed({ id: "inv-2", title: "Second" });
    mount();
    await screen.findByTestId("conversation"); // restored inv-1
    await open("inv-2"); // the seller then picks another: the restore must not fight it
    await waitFor(() => expect(sessionStorage.getItem("metrion.ceoHub.openInvestigation")).toBe("inv-2"));
  });
});

describe("agent status is shown only from evidence", () => {
  it("does not claim any agent is connected while availability is unknown or failed to load", async () => {
    const client = { ...fake.client(), getAvailability: async () => { throw new ApiError(500, "boom"); } };
    render(<CeoHubWorkspace client={client} feedFactory={feed.factory} />);
    expect(await screen.findByTestId("connected-row")).toHaveTextContent("Checking specialist availability…");
    for (const code of ["CI", "CFO", "PI", "CMO"]) expect(screen.getByTestId(`agent-node-${code}`)).toHaveAttribute("data-state", "UNKNOWN");
    expect(screen.queryByText(/\d+\/\d+ connected/)).not.toBeInTheDocument();
  });

  it("shows the real count once availability is known", async () => {
    mount();
    expect(await screen.findByText("4/4 connected")).toBeInTheDocument();
  });
});
