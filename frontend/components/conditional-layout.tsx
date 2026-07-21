"use client"

import { usePathname } from "next/navigation"
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { AppSidebar } from "@/components/app-sidebar"
import { CapabilitiesProvider, CapabilityGate } from "@/lib/capabilities"

const NO_SHELL_PATHS = ["/login"]

const OPTIONAL_ROUTES: Array<[prefix: string, capability: string]> = [
  // Help and troubleshooting routes remain readable even when the product
  // capability is disabled. Direct product routes below remain fail-closed.
  ["/connectors", "connectors"],
  ["/catalog", "catalog"],
  ["/query", "query"],
  ["/dashboards", "dashboards"],
  ["/pipelines", "pipelines"],
  ["/jobs", "pipelines"],
  ["/streaming", "streaming"],
  ["/notebooks", "notebooks"],
  ["/experiments", "experiments"],
]

const SELF_GATED_ROOT_ROUTES = new Set([
  "/pipelines",
  "/streaming",
  "/notebooks",
  "/experiments",
])

function OptionalRouteGate({ pathname, children }: { pathname: string; children: React.ReactNode }) {
  // These index pages already render their own CapabilityGate. Nested routes do
  // not, so they continue through the layout-level exact-or-prefix gate below.
  if (SELF_GATED_ROOT_ROUTES.has(pathname)) return <>{children}</>
  const match = OPTIONAL_ROUTES.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`))
  if (!match) return <>{children}</>
  return <CapabilityGate capability={match[1]}>{children}</CapabilityGate>
}

export function ConditionalLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const noShell = NO_SHELL_PATHS.some(p => pathname.startsWith(p))

  if (noShell) {
    return <>{children}</>
  }

  return (
    <CapabilitiesProvider>
      <SidebarProvider>
        <AppSidebar />
        <main className="flex-1 overflow-y-auto bg-muted/40">
          <div className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex h-14 items-center px-4">
              <SidebarTrigger />
            </div>
          </div>
          <OptionalRouteGate pathname={pathname}>{children}</OptionalRouteGate>
        </main>
      </SidebarProvider>
    </CapabilitiesProvider>
  )
}
