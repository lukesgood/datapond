"use client"

export interface AuthUser {
  id: string
  username: string
  display_name: string
  email: string
  role: "admin" | "viewer"
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

export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const e = await res.json()
    throw new Error(e.detail ?? "Login failed")
  }
  const data = await res.json()
  saveAuth(data.access_token, data.user)
  return data.user
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
  if ((window as any).__datapond_auth_interceptor) return
  ;(window as any).__datapond_auth_interceptor = true

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
    // Auto-logout on 401
    if (res.status === 401 && url.includes("/api/") && !url.includes("/api/auth/")) {
      clearAuth()
      window.location.href = "/login"
    }
    return res
  }
}
