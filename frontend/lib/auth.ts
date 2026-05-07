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
  return token ? { Authorization: `Bearer ${token}` } : {}
}
