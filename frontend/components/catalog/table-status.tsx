import NextLink from "next/link"
import { Copy, Database, GitBranch, Radio } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ago, browserHref, type TableFacts } from "@/lib/catalog-view"

/** What a table is besides its name, in the same words on the catalog rail and the
 *  table page: a read-only mirror (and of what), a live source table (not copied), or
 *  the source connection whose sync writes it. */
export function TableStatus({ facts, connectionId }: { facts: TableFacts; connectionId?: string | null }) {
  const lines = []
  if (facts.mirror_of) {
    lines.push(
      <li key="mirror" className="flex items-start gap-1.5">
        <GitBranch aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span><span className="font-medium text-foreground">Read-only mirror</span> of{" "}
          <NextLink href={browserHref(facts.mirror_of)} className="font-mono text-primary hover:underline">{facts.mirror_of}</NextLink>.
          {" "}Reads are answered by the owner; writes go there.</span>
      </li>)
  }
  if (facts.live) {
    lines.push(
      <li key="live" className="flex items-start gap-1.5">
        <Radio aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span><span className="font-medium text-foreground">Live from the source database</span>, not copied: every query reads it.
          {connectionId && <>{" "}<NextLink href={`/connectors/connections/${encodeURIComponent(connectionId)}`} className="text-primary hover:underline">Sync it into the lake</NextLink></>}</span>
      </li>)
  }
  if (facts.synced_from) {
    const s = facts.synced_from
    lines.push(
      <li key="sync" className="flex items-start gap-1.5">
        <Database aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Synced from{" "}
          <NextLink href={`/connectors/connections/${encodeURIComponent(s.connection_id)}`} className="text-primary hover:underline">{s.connection}</NextLink>
          {" "}· {ago(s.last_run_at)}{s.rows != null ? ` · ${s.rows.toLocaleString("en-US")} rows` : ""}
          {s.status && s.status !== "success" && <span className="text-[var(--dp-warn-text)]"> · last run {s.status}</span>}</span>
      </li>)
  }
  // A lake table nothing syncs: say so, rather than leave a "Managed" table with no
  // origin (live: the iceberg.public copies a 2.5 upgrade left behind).
  if (!lines.length && !facts.live && facts.origin_known !== false) {
    lines.push(
      <li key="none" className="flex items-start gap-1.5">
        <Database aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span><span className="font-medium text-foreground">No source writes this table.</span>{" "}
          It was made in Analytics, by an older sync target, or by another tool, and changes only when someone writes to it.</span>
      </li>)
  }
  if (!lines.length) return null
  return <ul className="space-y-1 text-xs text-muted-foreground">{lines}</ul>
}

/** Copy "catalog.namespace.table" to the clipboard. */
export function CopyName({ name }: { name: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button size="xs" variant="outline" aria-live="polite" title={`Copy ${name}`}
      onClick={async () => {
        try { await navigator.clipboard.writeText(name); setCopied(true); window.setTimeout(() => setCopied(false), 1500) }
        catch { /* clipboard refused: the name is on screen to select */ }
      }}>
      <Copy aria-hidden className="mr-1 h-3 w-3" />{copied ? "Copied" : "Copy name"}
    </Button>
  )
}
