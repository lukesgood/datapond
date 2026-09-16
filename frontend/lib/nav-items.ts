/** The sidebar's menu, as data.
 *
 *  Icons stay in the component: this module is imported by a unit test, and a test that
 *  had to pull React and lucide-react to check which pages the menu offers would be
 *  testing the wrong thing.
 */
export type NavItem = {
  title: string
  url: string
  capability?: string
  permission?: string
  external?: boolean
}

export type NavSection = {
  label: string
  hint: string
  items: NavItem[]
}

// Core product workflows stay visible in every profile. Optional data and workload
// modules fail closed until /api/capabilities explicitly enables them.
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Build AI",
    hint: "Ground and serve AI applications",
    items: [
      { title: "Knowledge", url: "/knowledge" },
      // "API", not "Connect". The dashboard's workflow already owns that word for step
      // 01 — connecting a data *source* — which is what it means everywhere else in a
      // data platform, and the menu item for it is Sources. Two opposite ends of the
      // pipeline cannot share a name. The URL stays /connect: /api is the backend
      // proxy prefix.
      //
      // ai:generate, not knowledge:read. knowledge:read covers viewer,
      // business_analyst, data_engineer and auditor — none of whom write an
      // application against the retrieval API.
      { title: "API", url: "/connect", permission: "ai:generate" },
    ],
  },
  {
    label: "Data",
    hint: "Optional ingestion, catalog, and query adapters",
    items: [
      { title: "Sources", url: "/connectors", capability: "connectors", permission: "connector:read" },
      { title: "Catalog", url: "/catalog", capability: "catalog" },
      { title: "Analytics", url: "/query", capability: "query", permission: "query:run" },
    ],
  },
  {
    label: "Pipelines",
    hint: "Optional transform and streaming workloads",
    items: [
      { title: "Transforms", url: "/pipelines", capability: "pipelines", permission: "pipeline:write" },
      { title: "Streaming", url: "/streaming", capability: "streaming", permission: "pipeline:write" },
    ],
  },
  {
    label: "Data Science",
    hint: "Optional notebooks and ML tracking",
    items: [
      { title: "Notebooks", url: "/notebooks", capability: "notebooks", permission: "workbench:read" },
      { title: "Experiments", url: "/experiments", capability: "experiments", permission: "workbench:read" },
    ],
  },
  {
    label: "Operate",
    hint: "Govern and run the foundation",
    items: [
      // Not in "Build AI", where it sat next to Knowledge. Nobody builds anything on
      // this page: it registers providers, issues keys, and reports spend — operator
      // actions, which is what this group is for.
      { title: "AI Gateway", url: "/ai", permission: "spend:read" },
      { title: "Governance", url: "/governance", permission: "governance:read" },
      { title: "Storage", url: "/storage", permission: "service:manage" },
      // Infrastructure = Services (workloads/adapters) + System (node) as one workspace
      // at /services with tabs; /system redirects into it.
      { title: "Infrastructure", url: "/services", permission: "service:manage" },
      { title: "Settings", url: "/settings", permission: "settings:write" },
    ],
  },
]

// Help = Guides + Documentation as one workspace at /help with tabs; /docs redirects.
export const BOTTOM_ITEMS: NavItem[] = [{ title: "Help", url: "/help" }]
