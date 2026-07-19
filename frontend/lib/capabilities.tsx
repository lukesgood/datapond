"use client"
import { createContext, useContext, useEffect, useState } from "react"
import Link from "next/link"
import { getProductProfile } from "@/lib/product-profile"

export type Capabilities = Record<string, boolean | string>

const CapsContext = createContext<Capabilities>({})

const CAPABILITY_LABELS: Record<string, string> = {
  connectors: "Sources",
  catalog: "Catalog",
  query: "SQL Lab",
  dashboards: "Dashboards",
  pipelines: "Transforms",
  streaming: "Streaming",
  experiments: "Experiments",
  notebooks: "Notebooks",
  lineage: "Lineage",
}

export function CapabilitiesProvider({ children }: { children: React.ReactNode }) {
  // Start empty. Core UI does not depend on flags; optional navigation and route
  // gates wait for an explicit true. `_loaded` distinguishes fetching from absent.
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
    const profile = getProductProfile(caps)
    const feature = CAPABILITY_LABELS[capability] ?? capability
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 p-16 text-center">
        <div className="rounded-full border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
          {profile.label}
        </div>
        <h2 className="text-lg font-semibold">{feature} is not enabled</h2>
        <p className="max-w-lg text-sm text-muted-foreground">
          The current deployment does not include the adapter or optional add-on required by this module.
          Disabling an OSS component does not automatically provision a cloud replacement.
        </p>
        <div className="flex flex-wrap justify-center gap-3 text-sm">
          <Link className="font-medium text-primary hover:underline" href="/docs/profiles">Compare deployment profiles</Link>
          <Link className="font-medium text-primary hover:underline" href="/services">View active services</Link>
        </div>
      </div>
    )
  }
  return <>{children}</>
}

// Optional capabilities fail closed: a module appears only after the backend
// explicitly reports true. Core callers can omit the key and remain available.
export function useCapability(key?: string): boolean {
  const caps = useContext(CapsContext)
  if (!key) return true
  return caps[key] === true
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
