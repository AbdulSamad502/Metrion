/** Client-side hint only — a rough visual nudge while typing. The real requirement
 * (10+ chars, zxcvbn score >= 2, HIBP breach check) is enforced server-side by Clerk;
 * this never blocks submission, it just gives feedback before the round-trip does.
 *
 * Deliberately length-led, not composition-led (no bonus for mixing in a symbol) — a
 * long passphrase is both easier to type correctly and harder to crack than a short
 * password stuffed with special characters, which is why Clerk itself isn't configured
 * to require any particular character class. */
export type PasswordStrength = { score: 0 | 1 | 2 | 3 | 4; label: string };

export function estimatePasswordStrength(password: string): PasswordStrength {
  if (!password) return { score: 0, label: "" };

  const variety =
    Number(/[a-z]/.test(password)) +
    Number(/[A-Z]/.test(password)) +
    Number(/[0-9]/.test(password)) +
    Number(/[^a-zA-Z0-9]/.test(password));

  let score: 0 | 1 | 2 | 3 | 4 = 0;
  if (password.length >= 16) score = 4;
  else if (password.length >= 13) score = 3;
  else if (password.length >= 10 && variety >= 2) score = 2;
  else if (password.length >= 10) score = 1;

  const label = ["Too short", "Weak", "Fair", "Good", "Strong"][score];
  return { score, label };
}
