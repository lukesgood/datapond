"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// Dashboards folded into the Analytics workspace (SQL Editor + Dashboards tabs).
// Keep this route as a redirect so existing links/bookmarks to /dashboards still
// land on the Dashboards tab. Individual dashboards keep their own /dashboards/[id]
// deep links.
export default function DashboardsRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/query?tab=dashboards") }, [router])
  return null
}
