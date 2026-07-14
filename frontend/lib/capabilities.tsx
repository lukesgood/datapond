"use client"
import { createContext, useContext, useEffect, useState } from "react"

export type Capabilities = Record<string, boolean | string>

const CapsContext = createContext<Capabilities>({})

export function CapabilitiesProvider({ children }: { children: React.ReactNode }) {
  // Start empty (fail-open): nothing hidden until we learn otherwise. `_loaded`
  // distinguishes "still fetching" from "fetched and this flag is false" so a
  // route gate can show a spinner instead of flashing a not-available state.
  const [caps, setCaps] = useState<Capabilities>({})
  useEffect(() => {
    fetch("/api/capabilities")
      .then((r) => (r.ok ? r.json() : {}))
      .then((c) => setCaps({ ...(c || {}), _loaded: true }))
      .catch(() => setCaps({ _loaded: true }))  // loaded, everything default-off-gated pages closed
  }, [])
  return <CapsContext.Provider value={caps}>{children}</CapsContext.Provider>
}

/** Fail-closed route guard for capability-gated pages. While capabilities are
 *  loading, renders a spinner; once loaded, renders children only when the
 *  capability is explicitly true, else a "not enabled on this profile" state.
 *  Prevents direct-URL access to pages whose backing service is disabled. */
export function CapabilityGate({ capability, children }: { capability: string; children: React.ReactNode }) {
  const caps = useContext(CapsContext)
  if (!caps._loaded) {
    return <div className="flex-1 flex items-center justify-center p-16 text-sm text-muted-foreground">Loading…</div>
  }
  if (caps[capability] !== true) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 p-16 text-center">
        <h2 className="text-lg font-semibold">Not enabled on this profile</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          This feature requires a component that isn’t deployed in the current
          (AWS AI Data Foundation) profile. It’s available in the full/on-prem profile.
        </p>
      </div>
    )
  }
  return <>{children}</>
}

// Returns true unless the capability is explicitly false (fail-open).
export function useCapability(key?: string): boolean {
  const caps = useContext(CapsContext)
  if (!key) return true
  return caps[key] !== false
}

// Fail-CLOSED: true only when the capability is explicitly true. A missing/unknown
// flag (e.g. a /api/capabilities fetch error, in which case caps stays {}) resolves
// to false. Use this for security/secure-context-sensitive gates — e.g. webauthn —
// where a network hiccup must never reveal gated UI. Mirrors the login page's
// `useState(false)` default for webauthn, which is fail-closed by construction.
export function useCapabilityStrict(key: string): boolean {
  const caps = useContext(CapsContext)
  return caps[key] === true
}

export function useCapabilities(): Capabilities {
  return useContext(CapsContext)
}
