"use client"

import {
  Home, Database, FlaskConical, Code2, Settings, Activity,
  Workflow, BarChart3, BookOpen, HelpCircle, FileCode,
  HardDrive, Radio, ArrowDownToLine, ShieldCheck, LogOut, User, GitBranch, Server,
  Sparkles,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { getUser, logout, type AuthUser } from "@/lib/auth"
import { useCapabilities } from "@/lib/capabilities"

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
}

type NavSection = {
  label: string
  hint: string
  items: NavItem[]
}

const mainSections: NavSection[] = [
  {
    label: "Collect",
    hint: "데이터 수집",
    items: [
      { title: "Ingestion",   url: "/connectors", icon: ArrowDownToLine, capability: "connectors" },
      { title: "Streaming",   url: "/streaming",  icon: Radio,           capability: "streaming" },
    ]
  },
  {
    label: "Transform",
    hint: "데이터 변환",
    items: [
      { title: "Transforms",  url: "/pipelines",  icon: GitBranch,  capability: "pipelines" },
      { title: "Catalog",     url: "/catalog",    icon: Database,   capability: "catalog" },
    ]
  },
  {
    label: "Analyze",
    hint: "데이터 분석",
    items: [
      { title: "Query Lab",    url: "/query",       icon: Code2,        capability: "query" },
      { title: "Knowledge",    url: "/knowledge",   icon: Sparkles },
      { title: "Notebooks",    url: "/notebooks",   icon: FileCode,     capability: "notebooks" },
      { title: "Experiments",  url: "/experiments", icon: FlaskConical, capability: "experiments" },
      { title: "Dashboards",   url: "/dashboards",  icon: BarChart3,    capability: "dashboards" },
    ]
  },
  {
    label: "Platform",
    hint: "",
    items: [
      { title: "Services",     url: "/services",    icon: Activity },
      { title: "System",       url: "/system",      icon: Server },
      { title: "Storage",      url: "/storage",     icon: HardDrive },
      { title: "Governance",   url: "/governance",  icon: ShieldCheck },
      { title: "Settings",     url: "/settings",    icon: Settings },
    ]
  },
]

const bottomItems = [
  { title: "Documentation", url: "/docs",  icon: BookOpen },
  { title: "Guides",        url: "/help",  icon: HelpCircle },
]

export function AppSidebar() {
  const pathname  = usePathname()
  const router    = useRouter()
  const [user, setUser] = useState<AuthUser | null>(null)
  const { setOpenMobile } = useSidebar()
  const caps = useCapabilities()

  useEffect(() => { setUser(getUser()) }, [])

  // Mobile: close the offcanvas sheet after navigating — otherwise the open
  // sheet hides the page the user just tapped to.
  useEffect(() => { setOpenMobile(false) }, [pathname, setOpenMobile])

  const isActive = (url: string) => pathname === url

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
            <p className="text-[10.5px] font-medium text-muted-foreground">AI Data Foundation</p>
          </div>
        </div>

        {/* Dashboard — top-level, no section label */}
        <div className="px-2 pb-1 shrink-0">
          <Link href="/dashboard">
            <SidebarMenuButton isActive={isActive("/dashboard")}>
              <Home />
              <span>Dashboard</span>
            </SidebarMenuButton>
          </Link>
        </div>

        {/* Main sections */}
        <div className="flex-1 overflow-y-auto">
          {mainSections.map((section) => {
            const visibleItems = section.items.filter(
              (item) => item.capability === undefined || caps[item.capability] !== false
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
                          <Link href={item.url}>
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
                <Link href={item.url}>
                  <SidebarMenuButton isActive={isActive(item.url)}>
                    <item.icon />
                    <span>{item.title}</span>
                  </SidebarMenuButton>
                </Link>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>

          {/* User info + logout */}
          {user && (
            <div className="mt-2 pt-2 border-t">
              <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-muted/50 group">
                <div className="h-7 w-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <User className="h-3.5 w-3.5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{user.display_name}</p>
                  <p className="text-[10px] text-muted-foreground capitalize">{user.role}</p>
                </div>
                <button
                  onClick={handleLogout}
                  aria-label="Sign out" title="Sign out"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-destructive/10 hover:text-destructive"
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
