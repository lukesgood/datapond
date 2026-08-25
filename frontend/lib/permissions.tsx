"use client"

import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { getToken } from "@/lib/auth"

/** What the signed-in user may do, per backend/app/permissions.py.
 *
 *  Served from /api/me/permissions rather than read off the token in localStorage:
 *  the menu should reflect the same source the API enforces from, and a value the
 *  browser owns is not that source. Hiding a menu is never the control anyway — the
 *  API refuses regardless — this only keeps people out of screens they cannot use.
 */
type PermissionState = { role: string; permissions: Set<string>; loaded: boolean }

const PermissionContext = createContext<PermissionState>({
  role: "viewer",
  permissions: new Set(),
  loaded: false,
})

export function PermissionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PermissionState>({
    role: "viewer",
    permissions: new Set(),
    loaded: false,
  })

  useEffect(() => {
    let cancelled = false
    // No credential, no request. This provider sits in the root layout, so it also
    // mounts on /login and /forgot; asking an authenticated endpoint there produced a
    // 401, which the fetch interceptor reads as an expired session — and /forgot is
    // not on the interceptor's suppression list, so password recovery bounced the
    // user back to the login screen.
    if (!getToken()) {
      setState(s => (s.loaded ? { role: "viewer", permissions: new Set(), loaded: false } : s))
      return
    }
    fetch("/api/me/permissions")
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (cancelled || !d) return
        setState({ role: d.role, permissions: new Set<string>(d.permissions), loaded: true })
      })
      .catch(() => {
        // Leave `loaded` false so gated items stay hidden — the same fail-closed
        // posture the capability gate uses when its fetch fails.
      })
    return () => { cancelled = true }
  }, [])

  return <PermissionContext.Provider value={state}>{children}</PermissionContext.Provider>
}

export function usePermissions() {
  return useContext(PermissionContext)
}

export function useHasPermission(permission?: string) {
  const { permissions, loaded } = usePermissions()
  if (!permission) return true
  return loaded && permissions.has(permission)
}
