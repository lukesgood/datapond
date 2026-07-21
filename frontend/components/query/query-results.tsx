"use client"

import { useState, useMemo } from "react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Download, Copy } from "lucide-react"

interface QueryResultsProps {
  columns?: string[]
  rows?: unknown[][]
  executionTime?: number
  loading?: boolean
}

const ROWS_PER_PAGE = 50

type CellType = "number" | "boolean" | "null" | "date" | "string"

// Detect value type for formatting and alignment
function detectType(value: unknown): CellType {
  if (value === null || value === undefined) return "null"
  if (typeof value === "boolean") return "boolean"
  if (typeof value === "number") return "number"
  if (typeof value === "string") {
    if (/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?/.test(value)) return "date"
    if (/^-?\d+(\.\d+)?$/.test(value)) return "number"
  }
  return "string"
}

// Detect column type from first non-null rows
function detectColumnType(rows: unknown[][], colIdx: number): CellType {
  for (const row of rows.slice(0, 20)) {
    const v = row[colIdx]
    if (v !== null && v !== undefined) return detectType(v)
  }
  return "string"
}

function formatValue(value: unknown, type: string): string {
  if (value === null || value === undefined) return ""
  if (type === "number" && typeof value === "number") {
    // Integer vs float
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 6 })
  }
  if (type === "date" && typeof value === "string") {
    try {
      const d = new Date(value)
      if (!isNaN(d.getTime())) {
        return value.includes("T")
          ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
          : d.toLocaleDateString(undefined, { dateStyle: "medium" })
      }
    } catch { /* fall through */ }
  }
  return String(value)
}

function copyToClipboard(columns: string[], rows: unknown[][]) {
  const header = columns.join("\t")
  const body = rows.map(row => row.map(v => v === null ? "" : String(v)).join("\t")).join("\n")
  navigator.clipboard.writeText(`${header}\n${body}`)
}

function downloadCSV(columns: string[], rows: unknown[][]) {
  const escape = (v: unknown) => {
    const s = v === null ? "" : String(v)
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"` : s
  }
  const header = columns.map(escape).join(",")
  const body = rows.map(r => r.map(escape).join(",")).join("\n")
  const blob = new Blob([`${header}\n${body}`], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `query-results-${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function QueryResults({
  columns = [],
  rows = [],
  executionTime,
  loading = false,
}: QueryResultsProps) {
  const [page, setPage] = useState(0)
  const [copied, setCopied] = useState(false)

  const totalPages = Math.ceil(rows.length / ROWS_PER_PAGE)
  const pageRows = rows.slice(page * ROWS_PER_PAGE, (page + 1) * ROWS_PER_PAGE)

  // Detect column types once
  const colTypes = useMemo(
    () => columns.map((_, i) => detectColumnType(rows, i)),
    [columns, rows]
  )

  const handleCopy = () => {
    copyToClipboard(columns, rows)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (loading) return null

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
        Query returned 0 rows
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 h-full min-h-0">
      {/* Toolbar */}
      <div className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{rows.length.toLocaleString()}</span> rows
          {executionTime !== undefined && (
            <span>· {executionTime < 1000 ? `${Math.round(executionTime)}ms` : `${(executionTime / 1000).toFixed(2)}s`}</span>
          )}
          <span>· {columns.length} columns</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={handleCopy}>
            <Copy className="h-3 w-3" />
            {copied ? "Copied!" : "Copy"}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={() => downloadCSV(columns, rows)}>
            <Download className="h-3 w-3" />
            CSV
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto rounded-md border min-h-0">
        <Table>
          <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur-sm z-10">
            <TableRow className="hover:bg-transparent">
              {columns.map((col, i) => (
                <TableHead
                  key={i}
                  className={`
                    h-8 text-xs font-semibold whitespace-nowrap px-3 border-r last:border-r-0
                    ${colTypes[i] === "number" ? "text-right" : "text-left"}
                  `}
                >
                  <div className="flex items-center gap-1.5">
                    {col}
                    <span className="text-muted-foreground/50 font-normal text-[10px] hidden sm:inline">
                      {colTypes[i] === "number" ? "#" : colTypes[i] === "date" ? "⏱" : ""}
                    </span>
                  </div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {pageRows.map((row, rowIdx) => (
              <TableRow key={rowIdx} className="hover:bg-muted/40 h-8">
                {row.map((cell, colIdx) => {
                  const type = colTypes[colIdx]
                  const isNull = cell === null || cell === undefined
                  const formatted = formatValue(cell, type)
                  return (
                    <TableCell
                      key={colIdx}
                      className={`
                        py-1 px-3 text-xs border-r last:border-r-0 align-middle
                        ${type === "number" ? "text-right font-mono tabular-nums" : ""}
                        ${type === "boolean" ? "text-center" : ""}
                        ${isNull ? "text-muted-foreground/40" : ""}
                      `}
                    >
                      {isNull ? (
                        <span className="italic text-[10px]">null</span>
                      ) : type === "boolean" ? (
                        <Badge
                          variant={cell ? "default" : "secondary"}
                          className="text-[10px] h-4 px-1"
                        >
                          {String(cell)}
                        </Badge>
                      ) : (
                        <span
                          className={`
                            block max-w-[400px] break-words leading-relaxed
                            ${type === "string" && formatted.length > 100 ? "whitespace-pre-wrap" : "whitespace-nowrap overflow-hidden text-ellipsis"}
                          `}
                          title={formatted.length > 60 ? formatted : undefined}
                        >
                          {formatted}
                        </span>
                      )}
                    </TableCell>
                  )
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between shrink-0 text-xs text-muted-foreground">
          <span>
            Rows {(page * ROWS_PER_PAGE + 1).toLocaleString()}–{Math.min((page + 1) * ROWS_PER_PAGE, rows.length).toLocaleString()} of {rows.length.toLocaleString()}
          </span>
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setPage(0)} disabled={page === 0}>
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setPage(p => p - 1)} disabled={page === 0}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="px-2 tabular-nums">{page + 1} / {totalPages}</span>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}>
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
