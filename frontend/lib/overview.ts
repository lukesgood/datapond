/** What the Overview page puts in "Needs attention" and "Get started".
 *
 *  Needs attention is one list built from three places: GET /api/ops/status (outages and
 *  failed syncs, each with its fix), the stale sources in the same response (grouped into
 *  one row that can sync them all), and agents whose keys stop them calling anything.
 */
import { issueView, type OpsAction, type OpsIssue, type StaleIssue } from "./ops-status.ts"
import { staleReasons } from "./source-freshness.ts"
import { liveKeys, type Agent } from "./agents.ts"

export type AttentionItem =
  | { kind: "issue"; key: string; title: string; detail: string; advice?: string; tone: "warn" | "info"; actions: OpsAction[] }
  | { kind: "stale"; key: string; title: string; detail: string; connectionIds: string[]
      sources: { id: string; name: string; reasons: string[] }[] }
  | { kind: "agent"; key: string; title: string; detail: string; href: string }

const EXPIRY_WARN_MS = 7 * 24 * 3_600_000

/** Agents set up but unable to call: active with no live key, or every key expiring within
 *  a week. A disabled agent is someone's choice and is not listed. */
export function agentProblems(agents: Agent[], now: Date): { id: string; name: string; text: string }[] {
  const out: { id: string; name: string; text: string }[] = []
  for (const a of agents) {
    if (!a.is_active) continue
    const name = a.display_name || a.username
    const live = liveKeys(a, now)
    if (live.length === 0) {
      out.push({ id: a.id, name, text: "No active key, so it cannot call anything yet." })
    } else if (live.every(k => k.expires_at !== null && new Date(k.expires_at).getTime() - now.getTime() <= EXPIRY_WARN_MS)) {
      const last = live.map(k => k.expires_at as string).sort().at(-1) as string
      out.push({ id: a.id, name, text: `Every key expires by ${last.slice(0, 10)}. Rotate or issue one before then.` })
    }
  }
  return out
}

export function attentionItems(
  issues: OpsIssue[], agents: { id: string; name: string; text: string }[], perms: Set<string>,
  now: number = Date.now(),
): AttentionItem[] {
  const out: AttentionItem[] = []
  issues.forEach((issue, i) => {
    if (issue.kind === "stale_source") return
    const v = issueView(issue, perms)
    out.push({ kind: "issue", key: `issue:${i}`, ...v })
  })
  const stale = issues.filter((i): i is StaleIssue => i.kind === "stale_source")
  if (stale.length) {
    const n = stale.length
    out.push({
      kind: "stale", key: "stale",
      title: `${n} ${n === 1 ? "source" : "sources"} missed a scheduled sync`,
      detail: stale.map(s => s.source).join(", "),
      connectionIds: stale.map(s => s.connection_id),
      // Each source with why: what run it missed, how old its data is, what happened last.
      sources: stale.map(s => ({
        id: s.connection_id, name: s.source,
        reasons: staleReasons({ status: "active", last_sync_at: null, ...s }, now).slice(0, -1),
      })),
    })
  }
  for (const a of agents) {
    out.push({ kind: "agent", key: `agent:${a.id}`, title: a.name, detail: a.text, href: `/agents/${encodeURIComponent(a.id)}` })
  }
  return out
}

/** "15:08" for today, "Nov 18, 15:08" before. */
export function lastCallLabel(iso: string | null | undefined, now: Date): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
  if (d.toDateString() === now.toDateString()) return time
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}, ${time}`
}

export type GetStartedStep = { key: string; label: string; href: string; done: boolean }

/** Each step is listed only when the page could tell whether it was done (`null` = unknown:
 *  a capability is off or the viewer may not read the source). All done → empty list. */
export function getStartedSteps(input: {
  sources: number | null
  queriedEver: boolean | null
  chunks: number | null
  agentsWithKey: number | null
}): GetStartedStep[] {
  const steps: GetStartedStep[] = []
  if (input.sources !== null) steps.push({ key: "source", label: "Connect a source", href: "/connectors?tab=marketplace", done: input.sources > 0 })
  if (input.queriedEver !== null) steps.push({ key: "query", label: "Query the lake", href: "/query", done: input.queriedEver })
  if (input.chunks !== null) steps.push({ key: "knowledge", label: "Add documents to Knowledge", href: "/knowledge", done: input.chunks > 0 })
  if (input.agentsWithKey !== null) steps.push({ key: "agent", label: "Connect an agent", href: "/agents/new", done: input.agentsWithKey > 0 })
  return steps.every(s => s.done) ? [] : steps
}

/** "2 lake catalogs, both reachable" / "2 lake catalogs, 1 unreachable". */
export function catalogFact(count: number, unreachable: number): string {
  const noun = `${count} lake catalog${count === 1 ? "" : "s"}`
  if (count === 0) return "None enabled"
  if (unreachable > 0) return `${noun}, ${unreachable} unreachable`
  return `${noun}, ${count === 1 ? "reachable" : count === 2 ? "both reachable" : "all reachable"}`
}
