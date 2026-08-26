/** A deliberately small Markdown subset — the parts a model actually emits.
 *
 *  The assistant panel rendered raw text, so `**bold**` reached the user as
 *  asterisks. Knowledge handled `**bold**` and nothing else, so lists arrived as
 *  lines beginning with a hyphen and headings as lines beginning with hashes.
 *
 *  No library. The dependency scan is a merge gate now, and a Markdown parser pulls
 *  in a tree of transitive packages to render six constructs in two chat bubbles.
 *  Parsing is separated from rendering so this half can be exercised directly.
 *
 *  Links are deliberately NOT clickable. In a cited answer the prose is derived from
 *  ingested documents, so a URL in it can come from whatever someone put in a file —
 *  turning that into an anchor makes the answer panel a phishing surface. The label
 *  and the URL are both shown as text; a person can still read and copy it.
 */

export type Inline =
  | { t: "text"; v: string }
  | { t: "bold"; v: string }
  | { t: "italic"; v: string }
  | { t: "code"; v: string }
  | { t: "cite"; v: string }

export type Block =
  | { t: "p"; spans: Inline[] }
  | { t: "h"; level: number; spans: Inline[] }
  | { t: "ul"; items: Inline[][] }
  | { t: "ol"; items: Inline[][] }
  | { t: "pre"; v: string }

// Order matters: code first, so `**` inside backticks stays literal.
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|(?<![*\w])\*[^*\n]+\*|\[\d+\])/g

export function parseInline(text: string, citations = false): Inline[] {
  const out: Inline[] = []
  for (const part of text.split(INLINE)) {
    if (!part) continue
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      out.push({ t: "code", v: part.slice(1, -1) })
    } else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      out.push({ t: "bold", v: part.slice(2, -2) })
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      out.push({ t: "italic", v: part.slice(1, -1) })
    } else if (citations && /^\[\d+\]$/.test(part)) {
      out.push({ t: "cite", v: part.slice(1, -1) })
    } else {
      out.push({ t: "text", v: part })
    }
  }
  return out
}

export function parseBlocks(text: string, citations = false): Block[] {
  const lines = (text ?? "").replace(/\r\n/g, "\n").split("\n")
  const blocks: Block[] = []
  let para: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null

  const flushPara = () => {
    if (para.length) {
      blocks.push({ t: "p", spans: parseInline(para.join(" ").trim(), citations) })
      para = []
    }
  }
  const flushList = () => {
    if (list) {
      blocks.push({
        t: list.ordered ? "ol" : "ul",
        items: list.items.map(i => parseInline(i, citations)),
      })
      list = null
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (line.trimStart().startsWith("```")) {
      flushPara(); flushList()
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) body.push(lines[i++])
      blocks.push({ t: "pre", v: body.join("\n") })
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      flushPara(); flushList()
      blocks.push({ t: "h", level: heading[1].length, spans: parseInline(heading[2], citations) })
      continue
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      flushPara()
      const ordered = Boolean(numbered)
      // A switch between bullets and numbers starts a new list rather than mixing
      // two meanings into one.
      if (list && list.ordered !== ordered) flushList()
      if (!list) list = { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
      continue
    }

    if (!line.trim()) { flushPara(); flushList(); continue }
    flushList()
    para.push(line.trim())
  }
  flushPara(); flushList()
  return blocks
}
