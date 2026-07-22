"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// Documentation folded into the Help workspace (Guides + Documentation tabs).
// Keep this route as a redirect so existing links/bookmarks to /docs still land
// on the Documentation tab. Individual articles keep their own /docs/[slug]
// deep links.
export default function DocsRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/help?tab=docs") }, [router])
  return null
}
