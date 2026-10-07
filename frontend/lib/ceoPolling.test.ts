import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FindingRow } from "@/lib/ceo";
import { startPollingFeed } from "@/lib/ceoPolling";

const row = (id: string): FindingRow => ({ id, source: "CFO", action_key: "k", status: "COMPLETE", figure_refs: [], report_ref: null, gap_reason: null, agent_run_id: null, created_at: "x" });

describe("startPollingFeed (the replaceable polling seam)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("polls on an interval and delivers what it fetched", async () => {
    const fetchFindings = vi.fn().mockResolvedValue([row("a")]);
    const onFindings = vi.fn();
    const feed = startPollingFeed({ fetchFindings, onFindings, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(onFindings).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchFindings).toHaveBeenCalledTimes(2);
    feed.stop();
  });

  it("never overlaps: a slow poll delays the next one instead of stacking", async () => {
    let release: (v: FindingRow[]) => void = () => undefined;
    const fetchFindings = vi.fn().mockImplementation(() => new Promise<FindingRow[]>((r) => (release = r)));
    const feed = startPollingFeed({ fetchFindings, onFindings: vi.fn(), intervalMs: 100 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000); // ten intervals pass while the first request is still open
    expect(fetchFindings).toHaveBeenCalledTimes(1);
    release([]);
    await vi.advanceTimersByTimeAsync(100);
    expect(fetchFindings).toHaveBeenCalledTimes(2);
    feed.stop();
  });

  it("reports a failed poll, keeps going, and never throws into the caller", async () => {
    const fetchFindings = vi.fn().mockRejectedValueOnce(new Error("blip")).mockResolvedValue([row("a")]);
    const onError = vi.fn();
    const onFindings = vi.fn();
    const feed = startPollingFeed({ fetchFindings, onFindings, onError, intervalMs: 50 });
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(50);
    expect(onFindings).toHaveBeenCalledWith([row("a")]);
    feed.stop();
  });

  it("stops cleanly: nothing fires after stop, even for an in-flight response", async () => {
    let release: (v: FindingRow[]) => void = () => undefined;
    const fetchFindings = vi.fn().mockImplementation(() => new Promise<FindingRow[]>((r) => (release = r)));
    const onFindings = vi.fn();
    const feed = startPollingFeed({ fetchFindings, onFindings, intervalMs: 10 });
    await vi.advanceTimersByTimeAsync(0);
    feed.stop();
    release([row("late")]);
    await vi.advanceTimersByTimeAsync(500);
    expect(onFindings).not.toHaveBeenCalled();
    expect(fetchFindings).toHaveBeenCalledTimes(1);
    feed.stop(); // idempotent
  });
});
