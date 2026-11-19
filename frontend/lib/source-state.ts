/** Which of the four states a fetched source is in. An error wins over stale data
 *  only when there is nothing to show; a failed refresh of data already on screen is
 *  the caller's to report beside it. */
export type SourceStatus = "loading" | "error" | "empty" | "ready"

export function sourceStatus({ loading, error, empty, hasData = !empty }: {
  loading: boolean
  error: string | null | undefined
  empty: boolean
  hasData?: boolean
}): SourceStatus {
  if (error && !hasData) return "error"
  if (loading && !hasData) return "loading"
  if (error) return "error"
  return empty ? "empty" : "ready"
}

/** The body of a response, or an Error saying what failed in words: the API's
 *  `detail` when it sent one, else the status. */
export async function readJson<T = unknown>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>
  let detail = ""
  try {
    const d = await res.json()
    if (d && typeof d.detail === "string") detail = d.detail
  } catch { /* not JSON */ }
  throw new Error(detail || statusText(res.status))
}

export function statusText(status: number): string {
  if (status === 401) return "your session has expired; sign in again"
  if (status === 403) return "your role does not allow this"
  if (status === 404) return "not found"
  if (status >= 500) return `the server failed (HTTP ${status})`
  return `HTTP ${status}`
}
