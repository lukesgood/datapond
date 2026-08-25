"use client"

import { parseBlocks, type Inline } from "@/lib/markdown"

/** Renders the Markdown subset a model actually emits.
 *
 *  Parsing lives in lib/markdown.ts so it can be exercised on its own; this file is
 *  only the mapping to elements. Nothing here interprets HTML — the parser produces
 *  a closed set of node types and each is rendered as a React element, so there is no
 *  path from model output to markup.
 */
export function Markdown({ text, citations = false, className = "" }: {
  text: string
  citations?: boolean
  className?: string
}) {
  const blocks = parseBlocks(text, citations)
  return (
    <div className={`space-y-2 ${className}`}>
      {blocks.map((b, i) => {
        if (b.t === "pre") return (
          <pre key={i} className="overflow-x-auto rounded-md border bg-muted/50 p-2 font-mono text-[11px] leading-relaxed">
            {b.v}
          </pre>
        )
        if (b.t === "h") {
          const size = b.level <= 2 ? "text-sm" : "text-[13px]"
          return <p key={i} className={`${size} font-semibold`}><Spans spans={b.spans} /></p>
        }
        if (b.t === "ul") return (
          <ul key={i} className="list-disc space-y-0.5 pl-4">
            {b.items.map((it, j) => <li key={j}><Spans spans={it} /></li>)}
          </ul>
        )
        if (b.t === "ol") return (
          <ol key={i} className="list-decimal space-y-0.5 pl-4">
            {b.items.map((it, j) => <li key={j}><Spans spans={it} /></li>)}
          </ol>
        )
        return <p key={i} className="whitespace-pre-wrap"><Spans spans={b.spans} /></p>
      })}
    </div>
  )
}

/** Inline spans only — for somewhere a block wrapper would be wrong. */
export function Spans({ spans }: { spans: Inline[] }) {
  return (
    <>
      {spans.map((s, i) => {
        if (s.t === "bold") return <strong key={i} className="font-semibold text-foreground">{s.v}</strong>
        if (s.t === "italic") return <em key={i}>{s.v}</em>
        if (s.t === "code") return (
          <code key={i} className="rounded bg-muted px-1 py-px font-mono text-[0.9em]">{s.v}</code>
        )
        if (s.t === "cite") return (
          <sup key={i} className="mx-0.5 inline-flex items-center rounded bg-primary/10 px-1 py-px align-baseline text-[10px] font-semibold text-primary">
            {s.v}
          </sup>
        )
        return <span key={i}>{s.v}</span>
      })}
    </>
  )
}
