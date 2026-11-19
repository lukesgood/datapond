"use client"

import { Suspense, useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"

/** The old wizard's address. New streams are made on the Streaming page now; links
 *  with ?source=kafka|kinesis|postgres-cdc land on the matching form. */
function Redirect() {
  const router = useRouter()
  const source = useSearchParams().get("source") ?? ""
  useEffect(() => {
    const kind = source.includes("kafka") ? "kafka" : source.includes("kinesis") ? "kinesis" : "cdc"
    router.replace(`/streaming?new=${kind}`)
  }, [router, source])
  return null
}

export default function NewStreamRedirect() {
  return <Suspense><Redirect /></Suspense>
}
