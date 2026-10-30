/** Sample dates are written relative to "now" so the sample data never looks stale. Dates only: no money or score is ever computed from them. */
const DAY = 86_400_000;
export const isoDaysAgo = (days: number, hour = 10): string => {
  const d = new Date(Date.now() - days * DAY);
  d.setUTCHours(hour, 0, 0, 0);
  return d.toISOString();
};
export const dateDaysAgo = (days: number): string => isoDaysAgo(days).slice(0, 10);
/** First and last day of the month `back` months before this one, as YYYY-MM-DD. */
export const monthBounds = (back: number): { start: string; end: string } => {
  const n = new Date();
  const start = new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth() - back, 1));
  const end = new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth() - back + 1, 0));
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
};
