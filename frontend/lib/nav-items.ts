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

// The menu follows the path data takes to an answer (docs/PRODUCT_CONCEPT.md v7):
// connect and land it (Data), say what it means (Semantic), use it — people and agents
// (Use) — and run the deployment underneath (Operate). Roles are not separate menus:
// each item is gated by its permission, so a role sees only its own stretch of the
// path (an analyst: Catalog → Semantic model → Analytics; an auditor: Governance), and
// help, guides and the demo describe one menu. Data and workload modules fail closed
// until /api/capabilities enables them, so a RAG-only profile starts at Use.
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Data",
    hint: "Connect sources, move and shape data, browse the catalog",
    items: [
      { title: "Sources", url: "/connectors", capability: "connectors", permission: "connector:read" },
      { title: "Transforms", url: "/pipelines", capability: "pipelines", permission: "pipeline:write" },
      // Tables, their metadata and the relationship graph.
      { title: "Catalog", url: "/catalog", capability: "catalog" },
    ],
  },
  {
    label: "Semantic",
    hint: "What the data means: metrics, joins and business concepts",
    items: [
      // Not /catalog/metrics: /catalog/[namespace] would shadow a namespace named
      // "metrics". Needs the query capability — a metric is computed by the engine.
      { title: "Semantic model", url: "/metrics", capability: "query", permission: "catalog:read" },
    ],
  },
  {
    label: "Use",
    hint: "Ask questions, search documents, notebooks and agents",
    items: [
      { title: "Analytics", url: "/query", capability: "query", permission: "query:run" },
      { title: "Knowledge", url: "/knowledge" },
      { title: "Notebooks", url: "/notebooks", capability: "notebooks", permission: "workbench:read" },
      { title: "Experiments", url: "/experiments", capability: "experiments", permission: "workbench:read" },
      // An agent is a governed caller (which data it reads, what it spends, what it
      // called); admin-only, like the service-account API behind it. How to connect one
      // (MCP, the gateway document, REST) is a guide, at /help/integrate.
      { title: "Agents", url: "/agents", permission: "user:manage" },
    ],
  },
  {
    label: "Operate",
    hint: "Govern and run the deployment",
    items: [
      { title: "Governance", url: "/governance", permission: "governance:read" },
      // Registers model providers, issues keys and reports spend.
      { title: "AI Gateway", url: "/ai", permission: "spend:read" },
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
