"use client"

import {
  Home, Database, FlaskConical, Code2, Settings, Activity,
  Workflow, BarChart3, BookOpen, HelpCircle, FileCode,
  HardDrive, Radio, ArrowDownToLine, GitMerge, LogOut, User,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { getUser, logout, type AuthUser } from "@/lib/auth"

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

const mainSections = [
  {
    label: "Data",
    items: [
      { title: "Ingestion",  url: "/connectors", icon: ArrowDownToLine },
      { title: "Streaming",  url: "/streaming",  icon: Radio },
      { title: "Pipelines",  url: "/pipelines",  icon: Workflow },
      { title: "Catalog",    url: "/catalog",    icon: Database },
    ]
  },
  {
    label: "Analyze",
    items: [
      { title: "Query Lab",    url: "/query",       icon: Code2 },
      { title: "Notebooks",    url: "/notebooks",   icon: FileCode },
      { title: "Experiments",  url: "/experiments", icon: FlaskConical },
      { title: "Dashboards",   url: "/dashboards",  icon: BarChart3 },
    ]
  },
  {
    label: "Platform",
    items: [
      { title: "Services",     url: "/services",             icon: Activity },
      { title: "Storage",      url: "/storage",              icon: HardDrive },
      { title: "Governance",   url: "http://datapond.local:30585", icon: GitMerge, external: true },
      { title: "Settings",     url: "/settings",             icon: Settings },
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

  useEffect(() => { setUser(getUser()) }, [])

  const isActive = (url: string) => pathname === url

  const handleLogout = async () => {
    await logout()
    router.push("/login")
  }

  return (
    <Sidebar>
      <SidebarContent className="flex flex-col h-full">
        {/* Logo */}
        <div className="px-4 py-5 shrink-0">
          <h1 className="text-xl font-bold">DataPond</h1>
          <p className="text-xs text-muted-foreground">AI-Native Lakehouse</p>
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
          {mainSections.map((section) => (
            <SidebarGroup key={section.label}>
              <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {section.items.map((item) => (
                    <SidebarMenuItem key={item.title}>
                      {(item as any).external ? (
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
          ))}
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
                  title="Sign out"
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
