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
  role: "admin" | "viewer"
  require_password_change?: boolean
}

const TOKEN_KEY = "datapond_token"
const USER_KEY  = "datapond_user"

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return localStorage.getItem(TOKEN_KEY)
}

export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function saveAuth(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  // Also save to cookie for middleware auth check
  document.cookie = `datapond_token=${token}; path=/; max-age=${24 * 3600}; SameSite=Lax`
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  document.cookie = "datapond_token=; path=/; max-age=0"
}

export function isAuthenticated(): boolean {
  return !!getToken()
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
    saveAuth(data.access_token, user)
    return user
  } catch {
    throw new Error("Sign-in succeeded, but the server returned an invalid response. Please try again.")
  }
}

export async function logout() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => {})
  clearAuth()
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  if (token) return { Authorization: `Bearer ${token}` }
  return {}
}

/**
 * Install a global fetch interceptor that auto-attaches the Bearer token
 * to all /api/ requests. Call once from a client component on mount.
 */
export function installAuthInterceptor() {
  if (typeof window === "undefined") return
  if (window.__datapond_auth_interceptor) return
  window.__datapond_auth_interceptor = true

  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url
    if (url.includes("/api/") && !url.includes("/api/auth/login")) {
      const token = getToken()
      if (token) {
        init = { ...(init ?? {}) }
        const existing: Record<string, string> = {}
        if (init.headers) {
          if (init.headers instanceof Headers) {
            init.headers.forEach((v, k) => { existing[k] = v })
          } else if (Array.isArray(init.headers)) {
            init.headers.forEach(([k, v]) => { existing[k] = v })
          } else {
            Object.assign(existing, init.headers)
          }
        }
        existing["Authorization"] = `Bearer ${token}`
        init.headers = existing
      }
    }
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
        // If we can't parse the body, check if token is actually expired
        const token = getToken()
        if (!token) {
          clearAuth()
          window.dispatchEvent(new Event("datapond:session-expired"))
        }
      }
    }
    return res
  }
}
