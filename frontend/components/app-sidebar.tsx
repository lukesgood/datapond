"use client"

import {
  Home, Database, FlaskConical, Code2, Settings, Activity,
  BarChart3, BookOpen, HelpCircle, FileCode,
  HardDrive, Radio, ArrowDownToLine, ShieldCheck, LogOut, User, GitBranch, Server,
  Sparkles, Bot,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { getUser, logout, type AuthUser } from "@/lib/auth"
import { useCapabilities } from "@/lib/capabilities"
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

type NavItem = {
  title: string
  url: string
  icon: React.ComponentType<{ className?: string }>
  capability?: string
  external?: boolean
  adminOnly?: boolean
}

type NavSection = {
  label: string
  hint: string
  items: NavItem[]
}

// Core product workflows stay visible in every profile. Optional data and
// workload modules fail closed until /api/capabilities explicitly enables them.
const mainSections: NavSection[] = [
  {
    label: "Build AI",
    hint: "Ground and serve AI applications",
    items: [
      { title: "Knowledge",  url: "/knowledge", icon: Sparkles },
      { title: "AI Gateway", url: "/ai",        icon: Bot, adminOnly: true },
    ],
  },
  {
    label: "Data",
    hint: "Optional ingestion, catalog, and query adapters",
    items: [
      { title: "Sources", url: "/connectors", icon: ArrowDownToLine, capability: "connectors" },
      { title: "Catalog", url: "/catalog",    icon: Database,        capability: "catalog" },
      { title: "SQL Lab", url: "/query",      icon: Code2,           capability: "query" },
    ],
  },
  {
    label: "Add-ons",
    hint: "Capability-gated data and ML workloads",
    items: [
      { title: "Transforms",  url: "/pipelines",   icon: GitBranch,      capability: "pipelines" },
      { title: "Streaming",   url: "/streaming",   icon: Radio,          capability: "streaming" },
      { title: "Dashboards",  url: "/dashboards",  icon: BarChart3,      capability: "dashboards" },
      { title: "Notebooks",   url: "/notebooks",   icon: FileCode,       capability: "notebooks" },
      { title: "Experiments", url: "/experiments", icon: FlaskConical,   capability: "experiments" },
    ],
  },
  {
    label: "Operate",
    hint: "Govern and run the foundation",
    items: [
      { title: "Governance", url: "/governance", icon: ShieldCheck },
      { title: "Storage",    url: "/storage",    icon: HardDrive },
      { title: "Services",   url: "/services",   icon: Activity },
      { title: "System",     url: "/system",     icon: Server },
      { title: "Settings",   url: "/settings",   icon: Settings, adminOnly: true },
    ],
  },
]

const bottomItems = [
  { title: "Documentation", url: "/docs",  icon: BookOpen },
  { title: "Guides",        url: "/help",  icon: HelpCircle },
]

export function AppSidebar() {
  const pathname  = usePathname()
  const router    = useRouter()
  const [user] = useState<AuthUser | null>(() => getUser())
  const { setOpenMobile } = useSidebar()
  const caps = useCapabilities()
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
            <h1 className="text-[15px] font-bold tracking-tight">DataPond</h1>
            <p className="text-[10.5px] font-medium text-muted-foreground">Portable AI Data Foundation</p>
          </div>
        </div>

        {/* Active deployment identity — metadata only; capabilities remain authoritative. */}
        <div className="mx-3 mb-3 rounded-lg border bg-muted/40 px-3 py-2" title={profile.description}>
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            <p className="truncate text-[11px] font-semibold">{profile.label}</p>
          </div>
          <p className="mt-0.5 truncate pl-3.5 text-[9.5px] capitalize text-muted-foreground">
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
                (!item.adminOnly || user?.role === "admin")
            )
            if (visibleItems.length === 0) return null
            return (
              <SidebarGroup key={section.label}>
                <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {visibleItems.map((item) => (
                      <SidebarMenuItem key={item.title}>
                        {item.external ? (
                          <a href={item.url} target="_blank" rel="noopener noreferrer">
                            <SidebarMenuButton>
                              <item.icon />
                              <span>{item.title}</span>
                            </SidebarMenuButton>
                          </a>
                        ) : (
                          <Link href={item.url} aria-current={isActive(item.url) ? "page" : undefined}>
                            <SidebarMenuButton isActive={isActive(item.url)}>
                              <item.icon />
                              <span>{item.title}</span>
                            </SidebarMenuButton>
                          </Link>
                        )}
                      </SidebarMenuItem>
                    ))}
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
                    <item.icon />
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
                    <p className="text-[10px] text-muted-foreground capitalize">{user.role}</p>
                  </div>
                </Link>
                <button
                  onClick={handleLogout}
                  aria-label="Sign out" title="Sign out"
                  className="rounded p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
