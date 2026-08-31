"use client"

import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { getToken } from "@/lib/auth"

/** One role the caller could be given, as served by GET /api/me/permissions'
 *  `assignable_roles` — a name, a one-line human label, and the permissions that
 *  role holds. See backend/app/permissions.py `ROLE_LABELS` / `ROLE_PERMISSIONS`:
 *  that module is the only place the label text is written down. */
export type AssignableRole = { name: string; label: string; permissions: string[] }

/** What the signed-in user may do, per backend/app/permissions.py.
 *
 *  Served from /api/me/permissions rather than read off the token in localStorage:
 *  the menu should reflect the same source the API enforces from, and a value the
 *  browser owns is not that source. Hiding a menu is never the control anyway — the
 *  API refuses regardless — this only keeps people out of screens they cannot use.
 */
type PermissionState = {
  role: string
  permissions: Set<string>
  loaded: boolean
  /** Every role the console may offer for someone else — same response, same fetch,
   *  so the settings page's role picker and this sidebar gate can never disagree
   *  about what the server currently accepts. */
  assignableRoles: AssignableRole[]
}

const PermissionContext = createContext<PermissionState>({
  role: "viewer",
  permissions: new Set(),
  loaded: false,
  assignableRoles: [],
})

export function PermissionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PermissionState>({
    role: "viewer",
    permissions: new Set(),
    loaded: false,
    assignableRoles: [],
  })

  useEffect(() => {
    let cancelled = false
    // No credential, no request. This provider sits in the root layout, so it also
    // mounts on /login and /forgot; asking an authenticated endpoint there produced a
    // 401, which the fetch interceptor reads as an expired session — and /forgot is
    // not on the interceptor's suppression list, so password recovery bounced the
    // user back to the login screen.
    // Nothing to reset: the initial state is already this, and the effect runs once
    // on mount. Writing it back was a synchronous setState inside an effect that
    // could only ever set what was already there.
    if (!getToken()) return
    fetch("/api/me/permissions")
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (cancelled || !d) return
        setState({
          role: d.role,
          permissions: new Set<string>(d.permissions),
          loaded: true,
          assignableRoles: Array.isArray(d.assignable_roles) ? d.assignable_roles : [],
        })
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
