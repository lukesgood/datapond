"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// System folded into the Infrastructure workspace (Services + System tabs).
// Keep this route as a redirect so existing links/bookmarks to /system still
// land on the System tab.
export default function SystemRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/services?tab=system") }, [router])
  return null
}
