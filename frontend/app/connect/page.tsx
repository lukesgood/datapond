"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// The "API & MCP" page became the integration guide (reference) plus the Agents
// page (keys). Kept as a redirect so existing links and bookmarks land on
// the guide.
export default function ConnectRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/help/integrate") }, [router])
  return null
}
