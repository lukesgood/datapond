"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Sparkles, Info } from "lucide-react"
import Link from "next/link"

export default function KnowledgeHelpPage() {
  return (
    <div className="flex-1 space-y-6 p-8 pt-6 max-w-5xl">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink href="/dashboard">Home</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbLink href="/help">Guides</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem><BreadcrumbPage>Knowledge &amp; RAG</BreadcrumbPage></BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex items-start gap-4">
        <div className="inline-flex p-3 rounded-lg bg-primary/10">
          <Sparkles className="h-8 w-8 text-primary" />
        </div>
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.14em] text-primary">Guide</p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight">Knowledge &amp; RAG</h1>
          <p className="mt-2 text-muted-foreground">
            Build a collection, check what it retrieves, and get answers that cite their sources
          </p>
        </div>
      </div>

      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>This path works in every profile</AlertTitle>
        <AlertDescription>
          Knowledge needs PostgreSQL with pgvector and a model provider through LiteLLM — nothing else.
          Catalog, SQL Lab and the optional add-ons can all be switched off and this guide still applies.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader><CardTitle>1. Create a collection</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            <Link href="/knowledge" className="text-primary hover:underline">Knowledge</Link> → New collection.
            A collection is the unit of access, of masking, and of refresh — one subject per collection rather
            than one big pile, because everything you govern later is governed at this boundary.
          </p>
          <p className="text-sm text-muted-foreground">
            Chunking belongs to the collection, not to each ingest. Set it once here; two ingests into one
            collection that split differently produce passages nothing reports as inconsistent.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>2. Ingest something representative</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">Three ways in, all landing in the same place:</p>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-primary/60">
            <li><span className="font-medium text-foreground">Paste or upload text</span> — fastest way to prove the path end to end.</li>
            <li><span className="font-medium text-foreground">S3 objects</span> — point at a configured bucket prefix.</li>
            <li>
              <span className="font-medium text-foreground">A catalog column</span> — in{" "}
              <Link href="/catalog" className="text-primary hover:underline">Catalog</Link>, pick a table and use
              Send to Knowledge. Choose a column that holds prose. A column of SKUs embeds perfectly well and
              retrieves nothing useful, which looks like broken retrieval and is a badly chosen source.
            </li>
          </ul>
          <p className="text-sm text-muted-foreground">
            Re-ingesting the same source replaces its chunks rather than appending, so running it twice does
            not double your collection.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>3. Search before you ask</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Use Search mode first and read the passages that come back. If the right passage is not in the
            results, no amount of prompting will put it in the answer — the model only ever sees what
            retrieval hands it.
          </p>
          <p className="text-sm text-muted-foreground">
            Retrieval is pgvector with an HNSW index. If a reranking model is configured the top results are
            reordered through it; when that model is unavailable the order falls back to plain vector
            similarity rather than failing the request.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>4. Ask, and check the citations</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Switch to Answer mode. Every answer comes back with the passages it was grounded on. An answer
            with no citations means the model had nothing to ground on — treat it as a retrieval problem,
            not a model problem.
          </p>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs"><code>{`curl -sX POST https://your-deployment/api/ai/rag \\
  -H "Authorization: Bearer $DATAPOND_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"collection": "support-knowledge-base", "question": "환불은 며칠 걸리나요?"}'`}</code></pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>5. Keep it fresh</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            A collection fed from a source can re-embed on an interval. The scheduler runs inside the backend
            — it does not need Airflow, and it holds a lock so replicas do not duplicate the work.
          </p>
          <p className="text-sm text-muted-foreground">
            Re-embedding costs model tokens every time it fires. Match the interval to how often the source
            actually changes; hourly on data that changes weekly is money spent on identical vectors.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>6. What gets masked on the way through</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            The guardrail runs on the question, on the retrieved passages, and on the generated answer.
            It covers Korean personal identifiers — 주민등록번호 and 신용카드 are checksum-verified, so random
            digits are not flagged — and structured credentials: AWS keys, PEM private keys, API tokens and
            database URLs.
          </p>
          <p className="text-sm text-muted-foreground">
            In <span className="font-mono text-foreground">mask</span> mode findings are replaced with a tag.
            In <span className="font-mono text-foreground">block</span> mode the answer is withheld and the
            citations still come back, so you can see what would have been used.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>7. Optional: widen a query with concepts</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            The Concepts tab lets you define a term and its synonyms — <em>refund</em> alongside 환불, 반품,
            환급 — and the Concepts toggle above the search box expands a query with them before retrieval.
            The results panel shows which concepts fired.
          </p>
          <p className="text-sm text-muted-foreground">
            It is off by default and does nothing until you add concepts. This is deliberate term expansion,
            not an inference engine: it widens recall for vocabulary your documents and your users spell
            differently.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>When something looks wrong</CardTitle></CardHeader>
        <CardContent>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground marker:text-primary/60">
            <li><span className="font-medium text-foreground">Search returns nothing</span> — check the collection actually has chunks, then that the embedding model has not changed. A different model means a different vector dimension.</li>
            <li><span className="font-medium text-foreground">Answers ignore an obvious document</span> — search for it directly. If search cannot find it, the problem is the source or the chunking, not the prompt.</li>
            <li><span className="font-medium text-foreground">Everything is masked</span> — the effective mode is the strictest of the deployment default, the collection, and the caller. A collection can tighten it; nothing can loosen it.</li>
            <li><span className="font-medium text-foreground">A scheduled refresh never runs</span> — confirm the collection has a saved source. A schedule without one has nothing to re-ingest.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
