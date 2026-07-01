"use client"

import { usePathname } from "next/navigation"
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { AppSidebar } from "@/components/app-sidebar"
import { CapabilitiesProvider } from "@/lib/capabilities"

const NO_SHELL_PATHS = ["/login"]

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
          {children}
        </main>
      </SidebarProvider>
    </CapabilitiesProvider>
  )
}
