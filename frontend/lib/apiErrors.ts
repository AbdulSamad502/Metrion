import { ApiError } from "@/lib/api";

/** A backend `detail` is shown only when it is a short, plain sentence: never a JSON payload, a stack trace or an internal identifier dump. */
function safeDetail(detail: unknown): string | null {
  if (typeof detail !== "string") return null;
  const t = detail.trim();
  if (!t || t.length > 160 || /[{}[\]\n\r]|traceback|exception|\w(?:Error|Exception)\b|\bat \S+:\d+/i.test(t)) return null;
  return t;
}

/** FastAPI's 422 body is a list of {loc, msg}. The first few are shown as "lines item 1 › listed_paise: Input should be a valid integer", so the seller can see which
 * field is wrong. The request value (`input`) is never shown, only the location and the validator's own short message. */
function validationReasons(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const parts: string[] = [];
  for (const item of detail) {
    if (!item || typeof item !== "object") continue;
    const { loc, msg } = item as { loc?: unknown; msg?: unknown };
    if (!Array.isArray(loc) || typeof msg !== "string" || !msg.trim() || msg.length > 120) continue;
    const path = loc
      .filter((p, i) => !(i === 0 && (p === "body" || p === "query" || p === "path")))
      .map((p) => (typeof p === "number" ? `item ${p + 1}` : String(p)))
      .join(" › ");
    parts.push(path ? `${path}: ${msg.trim()}` : msg.trim());
  }
  if (parts.length === 0) return null;
  return parts.slice(0, 3).join("; ") + (parts.length > 3 ? `; and ${parts.length - 3} more` : "");
}

const MAPPED: Record<number, string> = {
  402: "Your plan does not include this, or its limit for this period has been reached. Nothing was run or charged.",
  403: "You do not have permission to do this. Ask the account owner to grant you access.",
  409: "This conflicts with something already in progress or changed. Wait a moment, refresh and try again.",
  422: "Some details are missing or not valid. Check the form and try again.",
  503: "This feature is not available right now, or is not set up on the server yet. Nothing was sent and nothing was charged.",
  500: "Something went wrong on our side, not with what you entered. Nothing was changed on your account by this attempt. Try again; if it keeps failing, contact support.",
  502: "The server could not reach a service it depends on. Try again in a moment.",
  504: "The server took too long to answer. Try again; a large file or a slow model can need more than one attempt.",
};

/** One user-facing sentence for a failed request. 402, 403, 409, 422 and 503 get plain wording (plus the backend's own sentence when it is short and safe);
 * any other `ApiError` keeps its existing message; anything that is not an `ApiError` gets the caller's own fallback. Never returns raw JSON or internals. */
export function friendlyApiError(e: unknown, fallback: string): string {
  // A failed fetch (server down, offline, blocked) is a TypeError, not an ApiError: it is a connection problem, distinct from the server refusing the request.
  if (e instanceof TypeError) return "Could not reach the server. Check your connection, and that the backend is running, then try again.";
  if (!(e instanceof ApiError)) return fallback;
  const base = MAPPED[e.status];
  if (!base) return e.message.trim() || fallback; // an empty backend message must never become a silent, blank error
  const extra = safeDetail(e.detail) ?? (e.status === 422 ? validationReasons(e.detail) : null);
  return extra ? `${base} (${extra})` : base;
}
