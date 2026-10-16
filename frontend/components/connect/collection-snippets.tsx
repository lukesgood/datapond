"use client"

/** Search and cited-answer calls for one collection, its name already in place. Shown
 *  in the integration guide when it is opened for a collection
 *  (/help/integrate?collection=…, linked from Knowledge → the collection → Members);
 *  it was that collection's "Use from app" tab. */
import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { curlRag, curlSearch, pythonRag, snippetBase } from "@/lib/app-snippets"
import { useOrigin } from "@/components/connect/agent-reference"

export function CollectionSnippets({ name }: { name: string }) {
  const base = snippetBase(useOrigin())
  const [copied, setCopied] = useState<string | null>(null)

  const copy = async (label: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(label) } catch { setCopied(null) }
  }

  const blocks: [string, string][] = [
    ["Search (curl)", curlSearch(base, name)],
    ["Cited answer (curl)", curlRag(base, name)],
    ["Cited answer (Python)", pythonRag(base, name)],
  ]

  return (
    <div className="space-y-3">
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
    </div>
  )
}
