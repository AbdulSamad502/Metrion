/** Thin fetch wrapper for the FastAPI backend. Every call attaches the Clerk session
 * token as a bearer token — the backend's `require_auth()` (auth.md §7.1) verifies it
 * server-side; nothing here is a security boundary of its own. */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Request failed with ${status}`);
  }
}

export async function apiFetch<T>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export type SessionResponse = {
  appUserId: string;
  emailVerified: boolean;
  tenantId: string | null;
  membershipStatus: string | null;
  role: string | null;
  onboardingState: "PENDING_EMAIL_VERIFICATION" | "PENDING_ONBOARDING" | "ACTIVE";
};
