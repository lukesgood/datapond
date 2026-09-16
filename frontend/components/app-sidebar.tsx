"use client"

import {
  Home, Database, FlaskConical, Settings,
  BarChart3, HelpCircle, FileCode,
  HardDrive, Radio, ArrowDownToLine, ShieldCheck, LogOut, User, GitBranch, Server, Plug,
  Sparkles, Bot,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useSyncExternalStore } from "react"
import { logout, readUser, serverUser, subscribeToUser } from "@/lib/auth"
import { supportBadge, supportTier } from "@/lib/capability-support"
import { useCapabilities } from "@/lib/capabilities"
import { BOTTOM_ITEMS, NAV_SECTIONS } from "@/lib/nav-items"
import { usePermissions } from "@/lib/permissions"
import { getProductProfile } from "@/lib/product-profile"

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"


// Icons live here, not in lib/nav-items.ts: that module is imported by a unit test.
const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  "/knowledge": Sparkles, "/connect": Plug, "/connectors": ArrowDownToLine,
  "/catalog": Database, "/query": BarChart3, "/pipelines": GitBranch, "/streaming": Radio,
  "/notebooks": FileCode, "/experiments": FlaskConical, "/ai": Bot, "/governance": ShieldCheck,
  "/storage": HardDrive, "/services": Server, "/settings": Settings, "/help": HelpCircle,
}
const mainSections = NAV_SECTIONS
const bottomItems = BOTTOM_ITEMS

export function AppSidebar() {
  const pathname  = usePathname()
  const router    = useRouter()
  // Through useSyncExternalStore rather than a lazy useState: the server has no
  // localStorage, so an initialiser rendered no user block there and the browser
  // hydrated one in — React error #418 on every page this sidebar is on.
  const user = useSyncExternalStore(subscribeToUser, readUser, serverUser)
  const { setOpenMobile } = useSidebar()
  const caps = useCapabilities()
  const { permissions, loaded: permsLoaded } = usePermissions()
  const profile = getProductProfile(caps)

  // Mobile: close the offcanvas sheet after navigating — otherwise the open
  // sheet hides the page the user just tapped to.
  useEffect(() => { setOpenMobile(false) }, [pathname, setOpenMobile])

  const isActive = (url: string) => pathname === url || pathname.startsWith(`${url}/`)

  const handleLogout = async () => {
    await logout()
    router.push("/login")
  }

  return (
    <Sidebar>
      <SidebarContent className="flex flex-col h-full">
        {/* Logo */}
        <div className="px-4 py-5 shrink-0 flex items-center gap-2.5">
          <div className="dp-gradient relative h-8 w-8 shrink-0 overflow-hidden rounded-[9px] shadow-[0_4px_14px_-4px_var(--dp-aqua)]">
            <span className="pointer-events-none absolute inset-x-1.5 bottom-[7px] h-0.5 rounded bg-white/85
              shadow-[0_5px_0_rgba(255,255,255,.5),0_-5px_0_rgba(255,255,255,.35)]" />
          </div>
          <div className="min-w-0 leading-tight">
            <h1 className="text-base font-bold tracking-tight">DataPond</h1>
            <p className="text-2xs font-medium text-muted-foreground">Governed data tools for AI</p>
          </div>
        </div>

        {/* Active deployment identity — metadata only; capabilities remain authoritative. */}
        <div className="mx-3 mb-3 rounded-lg border bg-muted/40 px-3 py-2" title={profile.description}>
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--dp-good)]" />
            <p className="truncate text-2xs font-semibold">{profile.label}</p>
          </div>
          <p className="mt-0.5 truncate pl-3.5 text-2xs capitalize text-muted-foreground">
            {profile.maturity.replaceAll("-", " ")} · {profile.topology.replaceAll("-", " ")}
          </p>
        </div>

        {/* Overview (home) — top-level, no section label. Labeled "Overview" to match
            the page ("Overview / Foundation health") and avoid clashing with the
            "Dashboards" add-on (user-built custom dashboards). */}
        <div className="px-2 pb-1 shrink-0">
          <Link href="/dashboard" aria-current={isActive("/dashboard") ? "page" : undefined}>
            <SidebarMenuButton isActive={isActive("/dashboard")}>
              <Home />
              <span>Overview</span>
            </SidebarMenuButton>
          </Link>
        </div>

        {/* Main sections */}
        <div className="flex-1 overflow-y-auto">
          {mainSections.map((section) => {
            const visibleItems = section.items.filter(
              (item) =>
                (item.capability === undefined || caps[item.capability] === true) &&
                (item.permission === undefined || (permsLoaded && permissions.has(item.permission))) &&
                true
            )
            if (visibleItems.length === 0) return null
            return (
              <SidebarGroup key={section.label}>
                <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {visibleItems.map((item) => {
                      // A nav entry whose capability carries a support tier gets a
                      // small tag beside its title — the same fact /api/capabilities
                      // already reports, not a second opinion about it.
                      const tier = item.capability ? supportTier(item.capability, caps.support ?? {}) : null
                      const badge = tier ? supportBadge(tier) : null
                      return (
                      <SidebarMenuItem key={item.title}>
                        {item.external ? (
                          <a href={item.url} target="_blank" rel="noopener noreferrer">
                            <SidebarMenuButton>
                              {(() => { const Icon = ICONS[item.url]; return Icon ? <Icon /> : null })()}
                              <span>{item.title}</span>
                              {badge && (
                                <span title={badge.title}
                                      className="ml-auto rounded-full border px-1.5 py-0 text-2xs font-medium text-muted-foreground">
                                  {badge.label}
                                </span>
                              )}
                            </SidebarMenuButton>
                          </a>
                        ) : (
                          <Link href={item.url} aria-current={isActive(item.url) ? "page" : undefined}>
                            <SidebarMenuButton isActive={isActive(item.url)}>
                              {(() => { const Icon = ICONS[item.url]; return Icon ? <Icon /> : null })()}
                              <span>{item.title}</span>
                              {badge && (
                                <span title={badge.title}
                                      className="ml-auto rounded-full border px-1.5 py-0 text-2xs font-medium text-muted-foreground">
                                  {badge.label}
                                </span>
                              )}
                            </SidebarMenuButton>
                          </Link>
                        )}
                      </SidebarMenuItem>
                      )
                    })}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            )
          })}
        </div>

        {/* Bottom: Help / Docs + User */}
        <div className="px-2 py-3 border-t shrink-0 space-y-1">
          <SidebarMenu>
            {bottomItems.map((item) => (
              <SidebarMenuItem key={item.title}>
                <Link href={item.url} aria-current={isActive(item.url) ? "page" : undefined}>
                  <SidebarMenuButton isActive={isActive(item.url)}>
                    {(() => { const Icon = ICONS[item.url]; return Icon ? <Icon /> : null })()}
                    <span>{item.title}</span>
                  </SidebarMenuButton>
                </Link>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>

          {/* User: link to personal Account page + logout */}
          {user && (
            <div className="mt-2 pt-2 border-t">
              <div className="group flex items-center gap-1 rounded-md px-1 py-1.5">
                <Link
                  href="/account"
                  aria-current={isActive("/account") ? "page" : undefined}
                  className="flex flex-1 items-center gap-2 min-w-0 rounded-md px-1.5 py-1 hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
                >
                  <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <User className="h-3.5 w-3.5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <p className="text-xs font-medium truncate">{user.display_name}</p>
                    <p className="text-2xs text-muted-foreground capitalize">{user.role}</p>
                  </div>
                </Link>
                <button
                  onClick={handleLogout}
                  aria-label="Sign out" title="Sign out"
                  className="rounded p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      </SidebarContent>
    </Sidebar>
  )
}
