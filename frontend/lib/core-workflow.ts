/** The dashboard's "Core workflow" strip, as data.
 *
 *  Two steps lead somewhere different depending on which adapters a deployment runs,
 *  so this is a function of the capabilities rather than a constant. Icons stay in the
 *  component (see lib/nav-items.ts for why).
 */
export type WorkflowStepKind = "connect" | "organize" | "query" | "ground" | "agent" | "govern" | "ai"

export type WorkflowStep = {
  n: string
  title: string
  sub: string
  href: string
  kind: WorkflowStepKind
  cta?: boolean
}

export type WorkflowInputs = {
  sourcesEnabled: boolean
  catalogEnabled: boolean
  queryEnabled: boolean
  catalogBackend: string
  /** Enabled lake catalogs; more than one replaces the backend name in the sub-label. */
  lakeCatalogCount?: number
}

/** With a query engine the strip is the lakehouse path — land, catalog, query, govern,
 *  then AI on top. Without one (the RAG-only Portable Core) it is the knowledge path. */
export function coreWorkflowSteps({ sourcesEnabled, catalogEnabled, queryEnabled, catalogBackend, lakeCatalogCount = 0 }: WorkflowInputs): WorkflowStep[] {
  const connect: WorkflowStep = {
    n: "01",
    title: "Connect",
    sub: sourcesEnabled ? "Sources" : "Files, text & S3",
    href: sourcesEnabled ? "/connectors" : "/knowledge",
    kind: "connect",
  }
  const organize: WorkflowStep = {
    n: "02",
    title: "Organize",
    sub: catalogEnabled
      ? (lakeCatalogCount > 1 ? `${lakeCatalogCount} catalogs` : `${catalogBackend} catalog`)
      : "Knowledge collections",
    href: catalogEnabled ? "/catalog" : "/knowledge",
    kind: "organize",
  }
  if (queryEnabled) {
    return [
      connect,
      organize,
      { n: "03", title: "Query", sub: "SQL across the lake and sources", href: "/query", kind: "query", cta: true },
      { n: "04", title: "Govern", sub: "Access · masking · audit", href: "/governance", kind: "govern" },
      { n: "05", title: "Add AI", sub: "Search · cited answers · agents", href: "/knowledge", kind: "ai" },
    ]
  }
  return [
    connect,
    organize,
    { n: "03", title: "Ground", sub: "Embed · retrieve · rerank", href: "/knowledge", kind: "ground" },
    {
      n: "04",
      title: "Connect your agent",
      sub: "MCP, REST or an agent gateway",
      href: "/help/integrate",
      kind: "agent",
      cta: true,
    },
    { n: "05", title: "Govern", sub: "Access · PII · spend", href: "/governance", kind: "govern" },
  ]
}
