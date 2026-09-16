/** The dashboard's "Core workflow" strip, as data.
 *
 *  Two steps lead somewhere different depending on which adapters a deployment runs,
 *  so this is a function of the capabilities rather than a constant. Icons stay in the
 *  component (see lib/nav-items.ts for why).
 */
export type WorkflowStep = {
  n: string
  title: string
  sub: string
  href: string
  cta?: boolean
}

export type WorkflowInputs = {
  sourcesEnabled: boolean
  catalogEnabled: boolean
  catalogBackend: string
}

export function coreWorkflowSteps({ sourcesEnabled, catalogEnabled, catalogBackend }: WorkflowInputs): WorkflowStep[] {
  return [
    {
      n: "01",
      title: "Connect",
      sub: sourcesEnabled ? "Sources" : "Files, text & S3",
      href: sourcesEnabled ? "/connectors" : "/knowledge",
    },
    {
      n: "02",
      title: "Organize",
      sub: catalogEnabled ? `${catalogBackend} catalog` : "Knowledge collections",
      href: catalogEnabled ? "/catalog" : "/knowledge",
    },
    { n: "03", title: "Ground", sub: "Embed · retrieve · rerank", href: "/knowledge" },
    {
      n: "04",
      title: "Connect your agent",
      sub: "Issue a key, call this deployment",
      href: "/connect",
      cta: true,
    },
    { n: "05", title: "Govern", sub: "Access · PII · spend", href: "/governance" },
  ]
}
