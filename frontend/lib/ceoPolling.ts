import type { FindingRow } from "@/lib/ceo";

/** Progressive findings for B4 use the existing polling seam (`GET .../findings`). This is the ONLY place that knows that: the hub asks
 * for a `FindingsFeed` through a `FeedFactory`, so an SSE transport (B5+) is a drop-in replacement with the same two-method shape.
 *
 * Self-scheduling (the next poll is armed only after the previous one settles), so slow responses can never overlap. A failed poll is
 * reported and retried on the next tick; it never ends the feed and never affects the turn that is running. The interval is a UX
 * pacing constant, not a latency target. */
export type FindingsFeed = { stop: () => void };

export type FeedOptions = {
  fetchFindings: () => Promise<FindingRow[]>;
  onFindings: (findings: FindingRow[]) => void;
  onError?: (error: unknown) => void;
  intervalMs: number;
};

export type FeedFactory = (options: FeedOptions) => FindingsFeed;

export const POLL_INTERVAL_MS = 1500;

export const startPollingFeed: FeedFactory = ({ fetchFindings, onFindings, onError, intervalMs }) => {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const tick = async () => {
    if (stopped) return;
    try {
      const findings = await fetchFindings();
      if (!stopped) onFindings(findings);
    } catch (e) {
      if (!stopped) onError?.(e);
    }
    if (!stopped) timer = setTimeout(tick, intervalMs);
  };

  timer = setTimeout(tick, 0);
  return {
    stop: () => {
      stopped = true;
      if (timer !== null) clearTimeout(timer);
    },
  };
};
