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
      // How to connect an agent (MCP, the gateway document, the REST surface) is a
      // guide, at /help/integrate; issuing its key is on the Agents page.
      // A menu item that was a page of documentation with a copy of the key manager
      // sat between pages that do things. /connect redirects to the guide.
    ],
  },
  {
    label: "Data",
    hint: "Optional ingestion, catalog, and query adapters",
    items: [
      { title: "Sources", url: "/connectors", capability: "connectors", permission: "connector:read" },
      { title: "Catalog", url: "/catalog", capability: "catalog" },
      // Not /catalog/metrics: /catalog/[namespace] would shadow a namespace named
      // "metrics". Needs the query capability — a metric is computed by the engine.
      { title: "Metrics", url: "/metrics", capability: "query", permission: "catalog:read" },
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
      // First, and not under "Build AI": an agent is the unit being governed (which
      // data it reads, what it spends, what it called), and it may use metrics and
      // SQL, not only knowledge. Admin-only, like the service-account API behind it.
      { title: "Agents", url: "/agents", permission: "user:manage" },
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
