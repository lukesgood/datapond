/** Problem reports and feature requests (backend app/api/feedback.py): the shapes and
 *  the small rules both the Assistant form and Settings → Feedback use. */
export type FeedbackKind = "bug" | "feature"
export type FeedbackStatus = "open" | "planned" | "done" | "dismissed"

export interface FeedbackItem {
  id: string
  kind: FeedbackKind
  title: string
  body: string
  page: string | null
  app_version: string | null
  user_agent: string | null
  created_by: string | null
  created_by_name: string | null
  status: FeedbackStatus
  admin_note: string | null
  created_at: string
  updated_at: string
}

export const STATUS_LABEL: Record<FeedbackStatus, string> = {
  open: "Open", planned: "Planned", done: "Done", dismissed: "Dismissed",
}

export const KIND_LABEL: Record<FeedbackKind, string> = { bug: "Problem", feature: "Feature request" }

/** The page a report was filed from: the path only. A query string can hold SQL or
 *  data the reporter did not mean to send. */
export function reportPage(pathname: string): string {
  return (pathname || "/").split("?")[0].split("#")[0].slice(0, 500) || "/"
}

/** What the form sends; null when it cannot be sent yet. */
export function feedbackPayload(kind: FeedbackKind, title: string, body: string,
                                page: string, version: string | null, userAgent: string) {
  const t = title.trim()
  if (!t || t.length > 200 || body.length > 5000) return null
  return {
    kind, title: t, body: body.trim(), page: reportPage(page),
    app_version: version || null, user_agent: userAgent.slice(0, 300) || null,
  }
}
