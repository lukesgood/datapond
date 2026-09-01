"use client"

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
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
  /** True once a fetch of /api/me/permissions has come back failed — a bad status or
   *  a network error, as opposed to simply not having answered yet. `loaded` stays
   *  false in both cases (fail-closed: a gated control stays hidden either way), so
   *  this is the only thing that lets a caller tell "we asked and you may not" from
   *  "we could not ask" — see lib/permission-state.ts's permissionState, which is
   *  the rule that reads this field. */
  error: boolean
  /** Every role the console may offer for someone else — same response, same fetch,
   *  so the settings page's role picker and this sidebar gate can never disagree
   *  about what the server currently accepts. */
  assignableRoles: AssignableRole[]
}

const INITIAL_STATE: PermissionState = {
  role: "viewer",
  permissions: new Set(),
  loaded: false,
  error: false,
  assignableRoles: [],
}

const PermissionContext = createContext<PermissionState & { refetch: () => void }>({
  ...INITIAL_STATE,
  refetch: () => {},
})

export function PermissionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<PermissionState>(INITIAL_STATE)
  // Bumping this re-runs the effect below with the same token, so the "could not
  // check your permissions" state (components/ui/permission-state.tsx) has
  // something to retry into rather than a dead button.
  const [attempt, setAttempt] = useState(0)

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
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(d => {
        if (cancelled) return
        setState({
          role: d.role,
          permissions: new Set<string>(d.permissions),
          loaded: true,
          error: false,
          assignableRoles: Array.isArray(d.assignable_roles) ? d.assignable_roles : [],
        })
      })
      .catch(() => {
        if (cancelled) return
        // Leave `loaded` false so gated items stay hidden — the same fail-closed
        // posture the capability gate uses when its fetch fails. `error` is the new
        // part: it is what lets the UI say "we could not ask" instead of nothing.
        setState(s => ({ ...s, loaded: false, error: true }))
      })
    return () => { cancelled = true }
  }, [attempt])

  const refetch = useCallback(() => setAttempt(a => a + 1), [])

  return <PermissionContext.Provider value={{ ...state, refetch }}>{children}</PermissionContext.Provider>
}

export function usePermissions() {
  return useContext(PermissionContext)
}

export function useHasPermission(permission?: string) {
  const { permissions, loaded } = usePermissions()
  if (!permission) return true
  return loaded && permissions.has(permission)
}
