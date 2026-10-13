"use client"

declare global {
  interface Window {
    __datapond_auth_interceptor?: boolean
  }
}

export interface AuthUser {
  id: string
  username: string
  display_name: string
  email: string
  // Seeded roles; see backend/app/permissions.py for what each may do. An unknown
  // string is treated as "viewer" server-side rather than locking the account out.
  //
  // Present for display only (Account, the user-management table) — never branch
  // the console's own access decisions on it. This value lives in localStorage,
  // the browser's own JWT payload, so it carries no permissions and cannot express
  // a service account key's narrowed scopes; the API enforces from
  // GET /api/me/permissions, and lib/permissions.tsx's usePermissions()/
  // useHasPermission() read that same endpoint so the console can't disagree with
  // what the server will actually do. See lib/permission-source.test.ts, which
  // fails any page under app/ that compares this field with ===/!== to decide
  // what to render.
  role: string
  require_password_change?: boolean
}

// The session itself is an HttpOnly cookie (`datapond_token`) that the backend sets on
// sign-in and the browser sends by itself; nothing on the page can read it. Only the
// (non-secret) user is kept here, for display. LEGACY_TOKEN_KEY is where builds before
// 2026-10 kept the JWT; it is only ever removed.
const LEGACY_TOKEN_KEY = "datapond_token"
const USER_KEY  = "datapond_user"

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

// ── The signed-in user, for components that render it ─────────────────────────
//
// getUser() is fine inside an event handler or an effect. It is not fine as a value a
// component renders: the server has no localStorage, so `{user && …}` produces one HTML
// on the server and another in the browser, which React reports as hydration error #418
// on every page that component appears on. The sidebar did exactly that. A component
// that renders the user reads it with
//   useSyncExternalStore(subscribeToUser, readUser, serverUser)
// — the same arrangement lib/assistant-panel-state.ts uses for the same reason.

const userListeners = new Set<() => void>()

/** Subscribe to changes. A `storage` event covers another tab signing in or out;
 *  saveAuth() and clearAuth() notify this tab directly, because `storage` never fires in
 *  the tab that made the change. Returns the unsubscribe, as useSyncExternalStore expects. */
export function subscribeToUser(onChange: () => void) {
  userListeners.add(onChange)
  const hasWindow = typeof window !== "undefined"
  if (hasWindow) window.addEventListener("storage", onChange)
  return () => {
    userListeners.delete(onChange)
    if (hasWindow) window.removeEventListener("storage", onChange)
  }
}

let cachedRaw: string | null | undefined
let cachedUser: AuthUser | null = null

/** The stored user, or null. Returns the same object for as long as the stored value is
 *  unchanged: useSyncExternalStore compares snapshots by identity, and a fresh JSON.parse
 *  on every call would read as a change on every render. */
export function readUser(): AuthUser | null {
  let raw: string | null
  try {
    raw = localStorage.getItem(USER_KEY)
  } catch {
    // No localStorage (the server) or site data blocked — the same answer as signed out.
    return null
  }
  if (raw === cachedRaw) return cachedUser
  cachedRaw = raw
  try {
    cachedUser = raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    cachedUser = null
  }
  return cachedUser
}

/** The server cannot know who is signed in, so it renders signed out and the browser
 *  hydrates to whatever readUser() then reports. */
export function serverUser(): AuthUser | null {
  return null
}

function notifyUserChanged() {
  userListeners.forEach(fn => fn())
}

/** Remember who signed in. The session cookie was set by the response that carried
 *  `user`; this only records the person for the sidebar and the login page. */
export function saveAuth(user: AuthUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  notifyUserChanged()
}

/** Forget the signed-in user. The HttpOnly cookie is the backend's to clear
 *  (POST /api/auth/logout does); a stale one only ever answers 401. */
export function clearAuth() {
  localStorage.removeItem(LEGACY_TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  notifyUserChanged()
}

export function isAuthenticated(): boolean {
  return readUser() !== null
}

function errorField(value: unknown): string | null {
  if (!value || typeof value !== "object") return null
  const body = value as Record<string, unknown>
  for (const key of ["detail", "error", "message"]) {
    const candidate = body[key]
    if (
      typeof candidate === "string" &&
      candidate.trim().length > 0 &&
      candidate.trim().length <= 200 &&
      !/[<>\r\n]/.test(candidate) &&
      !/(traceback|stack trace|syntaxerror|jsondecode|unexpected token|expecting value|at position|internal server error)/i.test(candidate)
    ) {
      return candidate.trim()
    }
  }
  return null
}

function statusErrorMessage(status: number, fallback: string): string {
  const signingIn = fallback === "Sign-in failed"
  if (status === 400 || status === 422) return `${fallback}. Check the information you entered and try again.`
  if (status === 401) {
    return signingIn
      ? "The username or password is incorrect."
      : `${fallback}. Your session may have expired; sign in again and retry.`
  }
  if (status === 403) {
    return signingIn
      ? "This account is not permitted to sign in. Contact your administrator."
      : `${fallback}. You do not have permission to perform this action.`
  }
  if (status === 408 || status === 504) return `${fallback} because the request timed out. Please try again.`
  if (status === 429) return `${fallback} because there were too many attempts. Wait a moment and try again.`
  if (status >= 500) return `${fallback} because the service is temporarily unavailable. Please try again later.`
  return `${fallback}. Please try again.`
}

/** Read a JSON API error when safe, without exposing text/HTML proxy bodies. */
export async function responseErrorMessage(response: Response, fallback: string): Promise<string> {
  const statusMessage = statusErrorMessage(response.status, fallback)
  if (response.status >= 500 || response.status === 401 || response.status === 403 || response.status === 429) {
    return statusMessage
  }

  try {
    const text = (await response.text()).trim()
    if (!text) return statusMessage
    const parsed: unknown = JSON.parse(text)
    return errorField(parsed) ?? statusMessage
  } catch {
    return statusMessage
  }
}

export async function login(username: string, password: string): Promise<AuthUser> {
  let res: Response
  try {
    res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    })
  } catch {
    throw new Error("Unable to reach the sign-in service. Check your connection and try again.")
  }
  if (!res.ok) {
    throw new Error(await responseErrorMessage(res, "Sign-in failed"))
  }

  try {
    const data: { access_token?: unknown; user?: unknown } = await res.json()
    if (typeof data.access_token !== "string" || !data.user || typeof data.user !== "object") {
      throw new Error("invalid authentication response")
    }
    const user = data.user as AuthUser
    saveAuth(user)
    return user
  } catch {
    throw new Error("Sign-in succeeded, but the server returned an invalid response. Please try again.")
  }
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {})
  clearAuth()
}

/**
 * Install a global fetch interceptor that turns a 401 from the API into the
 * "session expired" event. The session cookie travels on its own (same-origin
 * fetch sends cookies by default), so nothing is added to the request.
 * Call once from a client component on mount.
 */
export function installAuthInterceptor() {
  if (typeof window === "undefined") return
  if (window.__datapond_auth_interceptor) return
  window.__datapond_auth_interceptor = true

  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url
    const res = await original(input, init)
    // Session expired on 401 — only if the response explicitly says "Not authenticated"
    // (avoid false positives from upstream service auth failures like Polaris OAuth)
    if (res.status === 401 && url.includes("/api/") && !url.includes("/api/auth/")) {
      try {
        const body = await res.clone().json()
        if (body?.detail === "Not authenticated" || body?.detail === "Invalid token" || body?.detail === "Token expired") {
          clearAuth()
          window.dispatchEvent(new Event("datapond:session-expired"))
        }
      } catch {
        // Not a JSON body: an upstream's 401, not ours.
      }
    }
    return res
  }
}
