/** Progress of a guided-input conversation, read from the question the backend asked.
 *
 * The backend writes "(N of M) " at the start of every question of a multi-question input session (`input_session._progress`). That is the
 * only place the position is reported, so this reads it back; when the prefix is absent (a single question, a plain decision card) there is
 * no progress and none is shown: nothing is estimated. These are question COUNTS, not money. */
export type Progress = { step: number; total: number; percent: number };

const PREFIX = /^\s*\((\d{1,3}) of (\d{1,3})\)\s/;

export function parseProgress(question: string): Progress | null {
  const m = PREFIX.exec(question);
  if (!m) return null;
  const step = parseInt(m[1], 10);
  const total = parseInt(m[2], 10);
  if (total < 1 || step < 1 || step > total) return null;
  return { step, total, percent: Math.round(((step - 1) / total) * 100) };
}
