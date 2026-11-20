import { kindShort } from "@/lib/catalog-view"

// The dot carries the kind's colour; the text stays in text ink so it reads in both themes.
const DOT: Record<string, string> = {
  glue: "bg-[var(--chart-5)]",
  polaris: "bg-[var(--chart-4)]",
  iceberg_rest: "bg-[var(--chart-2)]",
  trino_source: "bg-muted-foreground/50",
}

/** "Glue", "Polaris", "Iceberg REST" or "Source" beside a catalog's engine name. */
export function CatalogKindBadge({ kind, className = "" }: { kind?: string | null; className?: string }) {
  const label = kindShort(kind)
  if (!label || !kind) return null
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded border bg-background px-1.5 font-sans text-2xs font-medium leading-[18px] text-muted-foreground ${className}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${DOT[kind] ?? "bg-muted-foreground/50"}`} />
      {label}
    </span>
  )
}
