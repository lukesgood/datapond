"use client"

import { useCallback, useEffect, useState } from "react"
import { Download, Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { evidenceResult, maskedColumns, parsePiiEvidence, type PiiEvidence } from "@/lib/pii-evidence"

function fmt(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? "—"
    : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

/** "Personal data in the lake": per synced table, what was masked and whether a sample scan
 *  of the lake table found raw values. Evidence for a security review. */
export function PiiEvidenceSection() {
  const [data, setData] = useState<PiiEvidence | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (refresh: boolean) => {
    setScanning(true)
    setError(null)
    try {
      const res = await fetch(`/api/governance/pii-evidence${refresh ? "?refresh=true" : ""}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const parsed = parsePiiEvidence(await res.json())
      if (!parsed) throw new Error("unexpected response")
      setData(parsed)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setScanning(false)
    }
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void load(false), 0)
    return () => window.clearTimeout(t)
  }, [load])

  const exportNdjson = async () => {
    try {
      const res = await fetch("/api/governance/pii-evidence?format=ndjson")
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement("a")
      a.href = url
      a.download = "pii-evidence.ndjson"
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(`Export failed: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const tone = { good: "text-[var(--dp-good-text)]", warn: "text-[var(--dp-warn-text)] font-medium", muted: "text-muted-foreground" }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle className="text-base">Personal data in the lake</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">
            Samples {data?.sample_rows ?? 200} rows of each string column in every synced lake table and checks
            them for values that still look like personal data. Raw values are never shown.
            {data?.checked_at && ` Checked ${fmt(data.checked_at)}.`}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={() => void load(true)} disabled={scanning}>
            {scanning ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            Re-scan
          </Button>
          <Button variant="outline" size="sm" onClick={() => void exportNdjson()} disabled={!data}>
            <Download className="mr-2 h-4 w-4" />Export (NDJSON)
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {error && <p role="alert" className="px-6 pb-3 text-sm text-destructive">Could not load PII evidence: {error}</p>}
        {data && (
          <p className="px-6 pb-3 text-sm text-muted-foreground">
            {data.summary.tables} table{data.summary.tables === 1 ? "" : "s"} · {data.summary.ok} clean ·{" "}
            {data.summary.raw_found} with raw values · {data.summary.unverified} not verified
          </p>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Table</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Masked columns</TableHead>
              <TableHead>Last sync</TableHead>
              <TableHead>Result</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}><TableCell colSpan={5}><Skeleton className="h-4 w-full" /></TableCell></TableRow>
              ))
            ) : !data || data.tables.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  No synced tables yet. Sync a source to see its evidence here.
                </TableCell>
              </TableRow>
            ) : data.tables.map((t) => {
              const result = evidenceResult(t)
              const masked = maskedColumns(t)
              return (
                <TableRow key={t.table}>
                  <TableCell className="font-mono text-sm">{t.table}</TableCell>
                  <TableCell className="text-sm">{t.source}</TableCell>
                  <TableCell className="text-sm">{masked.length ? masked.join(", ") : "—"}</TableCell>
                  <TableCell className="text-sm">{fmt(t.last_run_at)}</TableCell>
                  <TableCell className={`text-sm ${tone[result.tone]}`}>{result.text}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
