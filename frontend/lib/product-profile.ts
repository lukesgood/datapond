import type { Capabilities } from "@/lib/capabilities"

export type ProductProfile = {
  id: string
  label: string
  description: string
  maturity: string
  topology: string
  adapters: string[]
}

function text(value: boolean | string | undefined): string {
  return typeof value === "string" ? value.trim() : ""
}

export function getProductProfile(caps: Capabilities): ProductProfile {
  const configuredLabel = text(caps.profile_label)
  const configuredId = text(caps.profile_id)
  const hasAwsAnalytics = caps.query_engine === "athena" || caps.catalog_backend === "glue"
  // The add-ons that put a module in this console — the reason a deployment reads as
  // extended rather than core. OpenMetadata is not among them: it is reachable at its
  // own URL and appears under Services, but it adds no page here, so a deployment
  // running it and nothing else is still a Portable Core console.
  const hasOssAddons = ["streaming", "pipelines", "experiments", "notebooks"].some(
    (key) => caps[key] === true,
  )

  const fallback = hasAwsAnalytics
    ? {
        id: "aws-managed",
        label: "AWS Managed Reference",
        description: "Portable Core with configured AWS data adapters.",
      }
    : hasOssAddons
      ? {
          id: "oss-extended",
          label: "OSS Extended",
          description: "Portable Core with self-hosted open-source add-ons.",
        }
      : {
          id: "portable-core",
          label: "Portable Core",
          description: "Governed RAG core with replaceable infrastructure contracts.",
        }

  const adapters = [
    text(caps.storage_provider),
    text(caps.catalog_backend),
    text(caps.query_engine),
    text(caps.vector_store),
    text(caps.model_gateway),
  ].filter((value, index, all) => value && value !== "none" && all.indexOf(value) === index)

  return {
    id: configuredId || fallback.id,
    label: configuredLabel || fallback.label,
    description: text(caps.profile_description) || fallback.description,
    maturity: text(caps.profile_maturity) || "custom",
    topology: text(caps.profile_topology) || "kubernetes",
    adapters,
  }
}
