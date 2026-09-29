/** How old a source's status is, in words an operator scans.
 *
 *  A source's status is the outcome of its last real contact — a sync that read it, an
 *  explicit check, a config save — and nothing polls in between. So "Active" alone
 *  overstates what is known: it means "answered when last asked". The age says when
 *  that was, and a check older than a day is marked stale rather than trusted.
 */
export const STALE_CHECK_MS = 86_400_000

export interface SourceCheck {
  text: string     // "checked 3h ago" | "never checked"
  stale: boolean   // never checked, or older than a day
}

export function describeCheck(lastCheckedAt: string | null | undefined, now: number): SourceCheck {
  if (!lastCheckedAt) return { text: "never checked", stale: true }
  const at = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(lastCheckedAt) ? lastCheckedAt : lastCheckedAt + "Z").getTime()
  if (!Number.isFinite(at)) return { text: "never checked", stale: true }
  const age = Math.max(0, now - at)
  const minutes = Math.floor(age / 60_000)
  const text = minutes < 1 ? "checked just now"
    : minutes < 60 ? `checked ${minutes}m ago`
    : minutes < 60 * 24 ? `checked ${Math.floor(minutes / 60)}h ago`
    : `checked ${Math.floor(minutes / (60 * 24))}d ago`
  return { text, stale: age > STALE_CHECK_MS }
}
