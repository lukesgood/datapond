"use client"

import {
  Home, Database, FlaskConical, Code2, Settings, Activity,
  Workflow, BarChart3, BookOpen, HelpCircle, FileCode,
  HardDrive, Radio, ArrowDownToLine,
} from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

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
      { title: "Services", url: "/services", icon: Activity },
      { title: "Storage",  url: "/storage",  icon: HardDrive },
      { title: "Settings", url: "/settings", icon: Settings },
    ]
  },
]

const bottomItems = [
  { title: "Documentation", url: "/docs",  icon: BookOpen },
  { title: "Guides",        url: "/help",  icon: HelpCircle },
]

export function AppSidebar() {
  const pathname = usePathname()

  const isActive = (url: string) => pathname === url

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
                      <Link href={item.url}>
                        <SidebarMenuButton isActive={isActive(item.url)}>
                          <item.icon />
                          <span>{item.title}</span>
                        </SidebarMenuButton>
                      </Link>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </div>

        {/* Bottom: Help / Docs */}
        <div className="px-2 py-3 border-t shrink-0">
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
        </div>
      </SidebarContent>
    </Sidebar>
  )
}
