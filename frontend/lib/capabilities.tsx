"use client"
import { createContext, useContext, useEffect, useState } from "react"

export type Capabilities = Record<string, boolean>

const CapsContext = createContext<Capabilities>({})

export function CapabilitiesProvider({ children }: { children: React.ReactNode }) {
  // Start empty (fail-open): nothing hidden until we learn otherwise.
  const [caps, setCaps] = useState<Capabilities>({})
  useEffect(() => {
    fetch("/api/capabilities")
      .then((r) => (r.ok ? r.json() : {}))
      .then((c) => setCaps(c || {}))
      .catch(() => setCaps({}))  // fail-open: keep {} → every item shown
  }, [])
  return <CapsContext.Provider value={caps}>{children}</CapsContext.Provider>
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
