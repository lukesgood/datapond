"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// Active Connections is now part of /connectors main page (first tab)
export default function ConnectionsRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/connectors") }, [router])
  return null
}
