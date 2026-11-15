/**
 * Presenter mode (public live inference, docs/DEPLOY.md "Presenter mode"). The team's own demo can paste the admin
 * token into the page (components/PresenterToken.tsx, shown only with `?presenter=1`) so its run / reveal requests
 * skip the per-IP limits and get queue priority on the server.
 *
 * Storage rules (tested in lib/presenter.test.mjs and e2e/presenter.spec.ts):
 * - sessionStorage ONLY (dies with the tab). Never localStorage, never the URL, never a cookie, never the bundle.
 * - Only the `openssl rand -hex 32` shape (64 lower-case hex) is stored; anything else is refused.
 * - The header is attached ONLY to POST /api/replay/run and POST /api/replay/{id}/reveal (lib/replay.ts,
 *   lib/benchmark.ts). No other request carries it.
 * Every storage access is wrapped: a blocked or missing sessionStorage just means "no presenter token".
 */

export const PRESENTER_TOKEN_KEY = "faultline.presenterToken";
/** Fired on window after the stored token changes, so the badge can update without polling. */
export const PRESENTER_EVENT = "faultline:presenter";
export const PRESENTER_TOKEN_PATTERN = /^[0-9a-f]{64}$/;

function session(): Storage | null {
  try {
    return typeof window !== "undefined" && window.sessionStorage ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function notify(): void {
  try {
    if (typeof window !== "undefined") window.dispatchEvent(new Event(PRESENTER_EVENT));
  } catch {
    /* no window events in this environment */
  }
}

/** The stored token, or null when none is stored (or the stored value is not token-shaped). */
export function getPresenterToken(): string | null {
  try {
    const value = session()?.getItem(PRESENTER_TOKEN_KEY) ?? null;
    return value !== null && PRESENTER_TOKEN_PATTERN.test(value) ? value : null;
  } catch {
    return null;
  }
}

/** Stores a token for this tab. Returns false (and stores nothing) when it is not 64 lower-case hex characters. */
export function setPresenterToken(raw: string): boolean {
  const token = raw.trim();
  if (!PRESENTER_TOKEN_PATTERN.test(token)) return false;
  const store = session();
  if (!store) return false;
  try {
    store.setItem(PRESENTER_TOKEN_KEY, token);
  } catch {
    return false;
  }
  notify();
  return true;
}

export function clearPresenterToken(): void {
  try {
    session()?.removeItem(PRESENTER_TOKEN_KEY);
  } catch {
    /* nothing stored */
  }
  notify();
}

/** `{Authorization: "Bearer <token>"}` when a presenter token is stored, else `{}`. Run and reveal only. */
export function presenterAuthHeader(): Record<string, string> {
  const token = getPresenterToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
