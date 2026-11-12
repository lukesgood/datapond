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

// DataPond is a lightweight lakehouse first (docs/PRODUCT_CONCEPT.md v7): the data
// platform leads, AI is a section on top of it, and operating the deployment closes the
// menu. Data and workload modules fail closed until /api/capabilities enables them, so a
// RAG-only profile (no catalog or engine) shows the AI section first in practice.
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Lakehouse",
    hint: "Iceberg catalog, SQL engine and data sources",
    items: [
      { title: "Catalog", url: "/catalog", capability: "catalog" },
      { title: "Analytics", url: "/query", capability: "query", permission: "query:run" },
      { title: "Sources", url: "/connectors", capability: "connectors", permission: "connector:read" },
      // Not /catalog/metrics: /catalog/[namespace] would shadow a namespace named
      // "metrics". Needs the query capability — a metric is computed by the engine.
      { title: "Metrics", url: "/metrics", capability: "query", permission: "catalog:read" },
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
    label: "AI",
    hint: "Search, cited answers and agents on top of your data",
    items: [
      // How to connect an agent (MCP, the gateway document, the REST surface) is a
      // guide, at /help/integrate; issuing its key is on the Agents page.
      { title: "Knowledge", url: "/knowledge" },
      // An agent is a governed caller (which data it reads, what it spends, what it
      // called); admin-only, like the service-account API behind it.
      { title: "Agents", url: "/agents", permission: "user:manage" },
      // Registers model providers, issues keys and reports spend.
      { title: "AI Gateway", url: "/ai", permission: "spend:read" },
    ],
  },
  {
    label: "Operate",
    hint: "Govern and run the deployment",
    items: [
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
