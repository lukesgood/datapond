"use client"

import {
  Home, Database, FlaskConical, Code2, Settings, Activity, Plug,
  Workflow, BarChart3, BookOpen, HelpCircle, FileCode, Boxes, GitBranch,
  HardDrive,
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

// Sidebar follows the natural data lifecycle:
// Ingest → Process → Catalog → Explore → Model → Visualize → Operate
const menuSections = [
  {
    label: "Overview",
    items: [
      { title: "Dashboard",    url: "/dashboard",   icon: Home },
    ]
  },
  {
    // 1단계: 데이터 수집 & 파이프라인
    label: "Data Engineering",
    items: [
      { title: "Connectors",   url: "/connectors",  icon: Plug },      // 외부 소스 연결
      { title: "Pipelines",    url: "/pipelines",   icon: Workflow },  // DAG 정의·실행
      { title: "Jobs",         url: "/jobs",         icon: GitBranch }, // 실행 이력·로그
      { title: "Data Catalog", url: "/catalog",     icon: Database },  // 테이블 탐색
      { title: "Storage",      url: "/storage",     icon: HardDrive }, // Object Storage
    ]
  },
  {
    // 2단계: 분석 → 노트북 → 실험 → 대시보드 (워크플로우 순서)
    label: "Analytics & Science",
    items: [
      { title: "Query Lab",       url: "/query",       icon: Code2 },       // SQL 탐색·분석
      { title: "Notebooks",       url: "/notebooks",   icon: FileCode },    // 코드 실험
      { title: "ML Experiments",  url: "/experiments", icon: FlaskConical },// 결과 추적·비교
      { title: "Dashboards",      url: "/dashboards",  icon: BarChart3 },   // 인사이트 공유
    ]
  },
  {
    // 3단계: 플랫폼 운영
    label: "Operations",
    items: [
      { title: "Services",  url: "/services",  icon: Activity },
      { title: "Settings",  url: "/settings",  icon: Settings },
    ]
  },
  {
    label: "Help",
    items: [
      { title: "Documentation", url: "/docs",  icon: BookOpen },
      { title: "Guides",        url: "/help",  icon: HelpCircle },
    ]
  }
]

export function AppSidebar() {
  const pathname = usePathname()

  return (
    <Sidebar>
      <SidebarContent>
        <div className="px-4 py-6">
          <h1 className="text-xl font-bold">DataPond</h1>
          <p className="text-xs text-muted-foreground">AI-Native Lakehouse</p>
        </div>

        {menuSections.map((section, idx) => (
          <SidebarGroup key={idx}>
            <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {section.items.map((item) => {
                  const isActive = pathname === item.url
                  return (
                    <SidebarMenuItem key={item.title}>
                      <Link href={item.url}>
                        <SidebarMenuButton isActive={isActive}>
                          <item.icon />
                          <span>{item.title}</span>
                        </SidebarMenuButton>
                      </Link>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
    </Sidebar>
  )
}
