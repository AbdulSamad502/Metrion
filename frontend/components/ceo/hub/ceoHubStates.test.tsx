import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { CeoHubWorkspace } from "@/components/ceo/hub/CeoHubWorkspace";
import { ApiError } from "@/lib/api";
import { FakeCeo, ManualFeed } from "@/test-support/fakeCeo";

let fake: FakeCeo;
let feed: ManualFeed;
beforeEach(() => {
  fake = new FakeCeo();
  feed = new ManualFeed();
});

describe("CEO Hub: the backend is unavailable", () => {
  it("says so once, in an alert with a retry, instead of looking like a normal empty start", async () => {
    const client = fake.client();
    let fail = true;
    const real = client.listInvestigations;
    client.listInvestigations = async () => {
      if (fail) throw new ApiError(503, {});
      return real();
    };
    render(<CeoHubWorkspace client={client} feedFactory={feed.factory} />);
    const banner = await screen.findByTestId("hub-unavailable");
    expect(banner).toHaveTextContent("Your conversations could not be loaded.");
    expect(banner.querySelector('[role="alert"]')).not.toBeNull();
    fail = false; // the backend is back
    await userEvent.setup().click(banner.querySelector("button")!);
    expect(screen.queryByTestId("hub-unavailable")).toBeNull();
  });

  it("shows no such banner when the list loads", async () => {
    fake.seed({ id: "inv-1", title: "Margins" });
    render(<CeoHubWorkspace client={fake.client()} feedFactory={feed.factory} />);
    await screen.findByTestId("ceo-hub");
    await screen.findByText("Your specialists");
    expect(screen.queryByTestId("hub-unavailable")).toBeNull();
  });
});
