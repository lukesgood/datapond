"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { curlRag, curlSearch, pythonRag, snippetBase } from "@/lib/app-snippets"
import { usePermissions } from "@/lib/permissions"

/** How an application or agent calls this collection. The key comes from
 *  Settings → Service accounts; this tab never shows a key, only where to get one. */
export function UseFromAppPanel({ name }: { name: string }) {
  const { role } = usePermissions()
  const [base, setBase] = useState("https://your-deployment")
  const [copied, setCopied] = useState<string | null>(null)
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setBase(snippetBase(window.location.origin)) }, [])

  const copy = async (label: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(label) } catch { setCopied(null) }
  }

  const blocks: [string, string][] = [
    ["Search (curl)", curlSearch(base, name)],
    ["Cited answer (curl)", curlRag(base, name)],
    ["Cited answer (Python)", pythonRag(base, name)],
  ]

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-base">1. Get a key for your agent</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            Each agent or application gets its own service account and key, so its reads, citations
            and spend are attributed to it and not to a person.
          </p>
          <p>
            {role === "admin"
              ? <>Issue one under <Link href="/connect" className="underline">API → Service accounts</Link> with scopes <code className="font-mono">knowledge:read</code> and <code className="font-mono">ai:generate</code>, then grant it this collection under the <b>Members</b> tab.</>
              : <>Ask an administrator for a service account with <code className="font-mono">knowledge:read</code> and <code className="font-mono">ai:generate</code>, granted this collection under the <b>Members</b> tab.</>}
          </p>
        </CardContent>
      </Card>
      {blocks.map(([label, text]) => (
        <Card key={label}>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">{label}</CardTitle>
            <Button size="sm" variant="outline" onClick={() => copy(label, text)}>
              {copied === label ? "Copied" : "Copy"}
            </Button>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs"><code>{text}</code></pre>
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground">
        Every call is logged against the key&apos;s service account and appears in Governance → Reports.
      </p>
    </div>
  )
}
