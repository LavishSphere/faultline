/**
 * Presenter mode (#222): on the presenter's own laptop, the chat sends the admin token so the person on stage is not
 * throttled with the whole venue (one shared address) or paused with everyone else.
 *
 * - Opened by visiting /explore/#presenter (or /#presenter); the token is pasted once into a prompt.
 * - Kept in this browser's localStorage only: never in the URL, a query string, the page text or an attribute.
 * - Sent as `Authorization: Bearer <token>` (routes/explore_chat.py `is_admin`) on the chat calls only: the API's CORS
 *   allows that header on exactly the four chat paths (main.PRESENTER_CORS_PATHS).
 * - "exit" removes it. Storage can be unavailable (private mode, blocked site data): then presenter mode is off.
 */

export const PRESENTER_KEY = "faultline.presenter.token";
export const PRESENTER_HASH = "#presenter";

export function getPresenterToken(): string | null {
  try {
    const t = globalThis.localStorage?.getItem(PRESENTER_KEY);
    return t && t.trim() ? t.trim() : null;
  } catch {
    return null;
  }
}

/** Saves the token; returns false when storage is unavailable (nothing is kept anywhere else). */
export function setPresenterToken(token: string): boolean {
  const t = token.trim();
  if (!t) return false;
  try {
    globalThis.localStorage.setItem(PRESENTER_KEY, t);
    return true;
  } catch {
    return false;
  }
}

export function clearPresenterToken(): void {
  try {
    globalThis.localStorage?.removeItem(PRESENTER_KEY);
  } catch {
    /* nothing stored */
  }
}

/** Headers for a chat request: Authorization when presenter mode is on, otherwise none. */
export function presenterHeaders(): Record<string, string> {
  const t = getPresenterToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
