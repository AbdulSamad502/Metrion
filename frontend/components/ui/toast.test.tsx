import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./Toast";

function Trigger() {
  const toast = useToast();
  return (
    <>
      <button onClick={() => toast.success("Saved.")}>ok</button>
      <button onClick={() => toast.error("Could not save.")}>bad</button>
    </>
  );
}
const setup = () => render(<ToastProvider><Trigger /></ToastProvider>);

describe("toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("announces a success politely and clears itself after five seconds", () => {
    setup();
    fireEvent.click(screen.getByText("ok"));
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
    act(() => void vi.advanceTimersByTime(5000));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps an error until it is dismissed, and says it as an alert", () => {
    setup();
    fireEvent.click(screen.getByText("bad"));
    act(() => void vi.advanceTimersByTime(60000));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save.");
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("waits while the pointer is over it, and shows one message at a time", () => {
    setup();
    fireEvent.click(screen.getByText("ok"));
    fireEvent.mouseEnter(screen.getByRole("status"));
    act(() => void vi.advanceTimersByTime(20000));
    expect(screen.getByRole("status")).toBeInTheDocument();
    fireEvent.click(screen.getByText("bad"));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("does nothing, and does not crash, outside a provider", () => {
    render(<Trigger />);
    fireEvent.click(screen.getByText("ok"));
    expect(screen.queryByRole("status")).toBeNull();
  });
});
