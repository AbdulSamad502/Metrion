/** Parses the `error` returned DIRECTLY from a Clerk Future-API call
 * (`const { error } = await signUp.password(...)`, etc), and turns Clerk's `code` into
 * copy a seller should actually read.
 *
 * Two rules this file exists to enforce, both learned from real bugs:
 *
 * 1. Never read the `errors` object off `useSignUp()`/`useSignIn()` inside the same async
 *    function that triggered it — that's reactive hook state, and reading it right after
 *    an `await` is a stale closure (the binding was captured before the call). Always
 *    parse the direct return value instead; it's never stale.
 *
 * 2. Never surface Clerk's raw `.message`/`.longMessage` as the user-facing string. Those
 *    are written for developers and logs — e.g. Clerk's own text for a stale/expired
 *    client-side attempt is literally "We were unable to complete a GET request for this
 *    Client. No sign up attempt was found. Please try again." That is not something to
 *    show a seller. Every error Clerk can return has a stable `.code`; this file maps the
 *    codes we know about to our own copy, and anything unrecognized gets one safe, generic
 *    message — never a passthrough of Clerk's internals.
 */

type ClerkErrorLike = {
  code?: string;
  message?: string;
  longMessage?: string;
  errors?: { code?: string; message?: string; longMessage?: string }[];
} | null;

const GENERIC_FALLBACK = "Something went wrong. Please try again.";

/** Errors that mean the local Clerk `Client`/sign-in/sign-up resource itself is stale,
 * abandoned, or no longer valid — e.g. a "check your email" tab left open for hours, or
 * state left over from an earlier attempt. No retry against the SAME in-memory resource
 * can fix this; the page needs a hard reload so the SDK re-initializes from scratch. */
const STALE_RESOURCE_CODES = new Set(["resource_not_found", "resource_forbidden", "client_mismatch"]);

const MESSAGES: Record<string, string> = {
  // Sign-up
  form_identifier_exists: "An account with this email already exists.",
  form_password_pwned: "That password has appeared in a known data breach. Please choose a different one.",
  form_password_compromised: "That password has appeared in a known data breach. Please choose a different one.",
  form_password_length_too_short: "Password must be at least 15 characters.",
  captcha_invalid: "We couldn't verify you're human. Please try again.",
  signup_rate_limit_exceeded: "Too many attempts. Please wait a moment and try again.",
  not_allowed_to_sign_up: "Sign-ups aren't currently open for this email address.",
  external_account_exists: "This Google account is already linked to a Metrion account.",

  // Sign-in
  form_identifier_not_found: "We couldn't find an account with that email.",
  form_password_incorrect: "That password is incorrect. Please try again.",
  strategy_for_user_invalid: "This account doesn't sign in with a password.",
  user_locked: "Too many failed attempts. This account is temporarily locked — please try again later or reset your password.",
  user_banned: "This account is no longer active.",
  user_deactivated: "This account has been deactivated.",
  session_exists: "You're already signed in.",

  // Verification codes (sign-up email code, password reset code)
  form_code_incorrect: "That code isn't right. Please check and try again.",
  verification_expired: "That code has expired. Request a new one.",
  verification_failed: "We couldn't verify that code. Request a new one.",

  // OAuth
  oauth_access_denied: "Google sign-in was cancelled.",

  // Generic rate limiting / abuse protection
  too_many_requests: "Too many attempts. Please wait a moment and try again.",
};

function firstError(error: unknown): { code?: string; message?: string; longMessage?: string } | null {
  if (!error || typeof error !== "object") return null;
  const e = error as ClerkErrorLike;
  return e?.errors?.[0] ?? (e?.code || e?.message ? e : null);
}

export function errorCode(error: unknown): string | undefined {
  return firstError(error)?.code;
}

/** True when the underlying Clerk resource (the in-progress sign-up/sign-in attempt, or
 * the Client itself) is stale/gone and no further calls against it can succeed — the UI
 * needs to force a fresh start, not just show an inline error. */
export function isStaleResourceError(error: unknown): boolean {
  const code = errorCode(error);
  return !!code && STALE_RESOURCE_CODES.has(code);
}

/** The ONE user-facing message for any Clerk error. Never echoes Clerk's raw text for an
 * unrecognized code — falls back to a safe generic sentence instead. */
export function errorText(error: unknown): string {
  const code = errorCode(error);
  if (code && MESSAGES[code]) return MESSAGES[code];
  return GENERIC_FALLBACK;
}

export function isIdentifierExistsError(error: unknown): boolean {
  return errorCode(error) === "form_identifier_exists";
}

/** Clerk refuses a sign-in/sign-up while this browser already holds a session — including a
 * "pending" one (unfinished session task), which `useAuth()` reports as signed-out, so the
 * page can't detect it up front. The caller should sign the stale session out and restart. */
export function isSessionExistsError(error: unknown): boolean {
  return errorCode(error) === "session_exists";
}

export function isWrongStrategyError(error: unknown): boolean {
  return errorCode(error) === "strategy_for_user_invalid";
}

/** Wraps a Clerk Future-API call so BOTH failure styles it can produce — a resolved
 * `{ error }` (the documented convention for expected validation failures) and a thrown
 * exception (what a broken/stale Client resource raises, since that's not a "form"
 * error) — end up in the same place. Every call site can then just check `.error`,
 * without an untried exception ever reaching React and, through Clerk's own console/error
 * surfacing, leaking raw internal text onto the page. */
export async function callClerk<T extends { error: unknown }>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (err) {
    return { error: err } as T;
  }
}

/** Same as `callClerk`, for the classic-API calls (`authenticateWithRedirect`, etc) that
 * resolve to `void` on success instead of `{ error }` — e.g. because success means "the
 * browser is already navigating away." */
export async function tryClerk(fn: () => Promise<unknown>): Promise<{ error: unknown }> {
  try {
    await fn();
    return { error: null };
  } catch (err) {
    return { error: err };
  }
}
