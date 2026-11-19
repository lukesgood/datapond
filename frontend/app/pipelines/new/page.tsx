"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

/** The retired visual builder's address. Its generated tasks were placeholders and
 *  its deploy was refused; new work starts in the SQL transform editor. */
export default function NewPipelineRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace("/pipelines?tab=transforms&edit=new") }, [router])
  return null
}
