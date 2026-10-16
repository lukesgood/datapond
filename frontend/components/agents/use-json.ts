"use client"

import { useCallback, useEffect, useState } from "react"

type State<T> = { data: T | null; error: string | null; status: number | null; loading: boolean }

/** GET a JSON route for one section of the agent page. Each section loads and fails
 *  on its own, so one slow or broken source never blanks the page: `error` is the
 *  server's `detail` when it sent one, and `reload` is the section's retry. Old data
 *  stays while a reload runs, so a save does not flash the section empty. */
export function useJson<T>(url: string) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, status: null, loading: true })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    fetch(url)
      .then(async r => {
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          if (!cancelled) setState(s => ({ ...s, error: typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`, status: r.status, loading: false }))
          return
        }
        const data = await r.json()
        if (!cancelled) setState({ data, error: null, status: r.status, loading: false })
      })
      .catch(e => {
        if (!cancelled) setState(s => ({ ...s, error: e instanceof Error ? e.message : "Could not load", status: null, loading: false }))
      })
    return () => { cancelled = true }
  }, [url, attempt])

  const reload = useCallback(() => setAttempt(n => n + 1), [])
  return { ...state, reload }
}
