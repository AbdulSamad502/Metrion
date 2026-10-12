import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import PiPage from "@/app/dashboard/pi/page";

describe("Product Intelligence form labels", () => {
  it("ties each label to its control so it names the control and clicking it focuses it", async () => {
    render(<PiPage />);
    const category = screen.getByLabelText("Category / product idea");
    expect(category.tagName).toBe("INPUT");
    expect(screen.getByLabelText(/Budget/)).toBeInstanceOf(HTMLInputElement);
    await userEvent.setup().click(screen.getByText("Category / product idea"));
    expect(category).toHaveFocus();
  });

  it("names the two inputs inside the one target-price field, with no duplicate ids", () => {
    render(<PiPage />);
    expect(screen.getByLabelText("Target minimum")).toBeInTheDocument();
    expect(screen.getByLabelText("Target maximum")).toBeInTheDocument();
    const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
