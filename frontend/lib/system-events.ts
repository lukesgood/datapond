/** Presentation logic for Infrastructure → Events.
 *
 *  Kept out of the component so it can be tested: `tsc` and `eslint` both pass on a
 *  summary line that is simply wrong, and collapsing repeats into one row is only
 *  worth doing if the row says how many and over how long.
 */

export interface SystemEvent {
  kind: string
  details?: Record<string, unknown> | null
}

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 }

export function severityRank(severity: string): number {
  // Unknown sorts last: a severity we do not recognise is not evidence of urgency.
  return severity in SEVERITY_ORDER ? SEVERITY_ORDER[severity] : 99
}

function span(fromIso: string, toIso: string): string | null {
  const ms = Date.parse(toIso) - Date.parse(fromIso)
  if (!Number.isFinite(ms) || ms < 60_000) return null
  const minutes = Math.round(ms / 60_000)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

export function summarizeOccurrences(count: number, firstSeen: string, lastSeen: string): string {
  if (count <= 1) return "once"
  const over = span(firstSeen, lastSeen)
  return over ? `${count} times over ${over}` : `${count} times`
}

export function causeNote(event: SystemEvent): string | null {
  // Only the events we inferred after the fact carry this. Everything else observed
  // its own cause and does not need the caveat.
  if (event.kind !== "node_reboot") return null
  if (event.details?.cause_recorded !== false) return null
  return "Cause not recorded — nothing collects while the backend is down. Check CloudWatch or the EC2 console."
}
