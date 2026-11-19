/** Notebooks list: sorting, which notebook a running kernel belongs to, and when. */

export type NotebookRow = { name: string; path: string; last_modified?: string | null; type?: string }
export type Session = {
  id: string; name: string; path: string; type: string
  kernel?: { id: string; name: string; execution_state?: string | null; connections?: number; last_activity?: string | null } | null
}
export type NotebookSort = "changed" | "name"

export function sortNotebooks<T extends NotebookRow>(rows: T[], sort: NotebookSort, query: string): T[] {
  const q = query.trim().toLowerCase()
  const kept = q ? rows.filter(r => r.path.toLowerCase().includes(q)) : rows
  return [...kept].sort((a, b) => sort === "name"
    ? a.name.localeCompare(b.name)
    : (Date.parse(b.last_modified ?? "") || 0) - (Date.parse(a.last_modified ?? "") || 0))
}

/** The session running this notebook, if any. Jupyter reports the path it opened. */
export function sessionFor(path: string, sessions: Session[]): Session | null {
  return sessions.find(s => s.path === path) ?? null
}

/** The kernel's own display name ("python3" → "Python 3"); never a guess for a
 *  notebook with no kernel running. */
export function kernelLabel(name: string | undefined | null): string {
  if (!name) return ""
  const m = /^python(\d+)?$/i.exec(name)
  if (m) return `Python${m[1] ? ` ${m[1]}` : ""}`
  return name
}

export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  const t = Date.parse(iso ?? "")
  if (!t) return "—"
  const min = Math.round((now.getTime() - t) / 60_000)
  if (min < 1) return "just now"
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.round(h / 24)
  if (d < 7) return `${d} day${d === 1 ? "" : "s"} ago`
  return new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

/** "managed" (an external service DataPond does not probe) is not "offline". */
export function jupyterState(status: string | undefined): { label: string; tone: "good" | "bad" | "muted"; canOpen: boolean } {
  if (status === "healthy") return { label: "running", tone: "good", canOpen: true }
  if (status === "managed") return { label: "managed outside DataPond", tone: "muted", canOpen: true }
  if (status === "unhealthy") return { label: "unavailable", tone: "bad", canOpen: false }
  return { label: "status unknown", tone: "muted", canOpen: true }
}

export function withIpynb(name: string): string {
  const n = name.trim()
  return n.endsWith(".ipynb") ? n : `${n}.ipynb`
}

/** JupyterLab's own address for one notebook. */
export function labUrl(base: string, path: string): string {
  return `${base}/lab/tree/${path.split("/").map(encodeURIComponent).join("/")}`
}
