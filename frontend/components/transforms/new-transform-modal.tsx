"use client"

import { useEffect, useState } from "react"
import { useToast } from "@/lib/toast"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { AlertCircle, Loader2, Rocket } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"

const NAMESPACES = ["raw", "refined", "serving"]
const SCHEDULES = [
  { label: "Manual only", value: "" },
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every 6 hours", value: "0 */6 * * *" },
  { label: "Daily (midnight)", value: "0 0 * * *" },
  { label: "Weekly (Sunday)", value: "0 0 * * 0" },
]

const SQL_PLACEHOLDER = `-- Write your transformation SQL here.
-- Source tables: iceberg.<source_namespace>.<table_name>
-- The result will be written to iceberg.<target_namespace>.<target_table>

SELECT
  id,
  name,
  amount,
  status,
  CURRENT_TIMESTAMP AS transformed_at
FROM iceberg.raw.orders
WHERE status = 'completed'`

export interface EditingTransform {
  id: string
  name: string
  description: string | null
  source_namespace: string
  target_namespace: string
  target_table: string
  sql: string
  schedule: string | null
}

interface Props {
  open: boolean
  onClose: () => void
  onCreated: () => void
  editing?: EditingTransform | null   // 지정 시 수정 모드(이름 고정, overwrite 배포)
}

export function NewTransformModal({ open, onClose, onCreated, editing }: Props) {
  const [name, setName]                       = useState("")
  const [description, setDescription]         = useState("")
  const [sourceNs, setSourceNs]               = useState("raw")
  const [targetNs, setTargetNs]               = useState("refined")
  const [targetTable, setTargetTable]         = useState("")
  const [sql, setSql]                         = useState("")
  const [schedule, setSchedule]               = useState("")
  const [submitting, setSubmitting]           = useState(false)
  const [error, setError]                     = useState<string | null>(null)
  const [sourceNamespaces, setSourceNamespaces] = useState<string[]>(NAMESPACES)

  // T6: 소스는 카탈로그의 실제 네임스페이스 목록(실데이터가 default 등에 존재)
  useEffect(() => {
    if (!open) return
    fetch("/api/catalog/schemas?columns=false")
      .then(r => r.json())
      .then(d => {
        const response = d as { catalogs?: Array<{ schemas?: Array<{ name?: string }> }> }
        const names = (response.catalogs ?? [])
          .flatMap(c => c.schemas ?? [])
          .map(schema => schema.name)
          .filter((name): name is string => typeof name === "string")
        const merged = Array.from(new Set([...names, ...NAMESPACES])).sort()
        if (merged.length) setSourceNamespaces(merged)
      })
      .catch(() => {})
  }, [open])

  // T4: 수정 모드 — 기존값 프리필
  useEffect(() => {
    if (!open || !editing) return
    const timer = setTimeout(() => {
      setName(editing.name); setDescription(editing.description || "")
      setSourceNs(editing.source_namespace); setTargetNs(editing.target_namespace)
      setTargetTable(editing.target_table); setSql(editing.sql); setSchedule(editing.schedule || "")
    }, 0)
    return () => clearTimeout(timer)
  }, [open, editing])

  const valid = name.trim() && targetTable.trim() && sql.trim() && sourceNs !== targetNs

  const { toast } = useToast()
  const handleSubmit = async () => {
    if (!valid) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch("/api/transforms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          source_namespace: sourceNs,
          target_namespace: targetNs,
          target_table: targetTable.trim(),
          sql: sql.trim(),
          schedule: schedule || null,
          overwrite: !!editing,
        }),
      })
      const data = await res.json() as { detail?: string }
      if (!res.ok) throw new Error(data.detail || "Failed to create transform")
      toast(`Transform '${name.trim()}' ${editing ? "수정 배포됨" : "배포됨"} — Airflow DAG ${editing ? "갱신" : "생성"} 완료`, "success")
      onCreated()
      handleClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create transform")
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    setName(""); setDescription(""); setSourceNs("raw"); setTargetNs("refined")
    setTargetTable(""); setSql(""); setSchedule(""); setError(null)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit Transform — ${editing.name}` : "New Transform"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-1">
          {/* Name + Description */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs">Name <span className="text-destructive">*</span></Label>
              <Input
                placeholder="orders_refined"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={!!editing}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Description</Label>
              <Input
                placeholder="Clean and aggregate orders"
                value={description}
                onChange={e => setDescription(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
          </div>

          {/* Namespace row */}
          <div className="grid grid-cols-3 gap-3 items-end">
            <div className="space-y-1.5">
              <Label className="text-xs">Source Namespace <span className="text-destructive">*</span></Label>
              <Select value={sourceNs} onValueChange={(v) => v && setSourceNs(v)}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sourceNamespaces.map(ns => (
                    <SelectItem key={ns} value={ns} className="text-sm font-mono">{ns}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center justify-center pb-1">
              <span className="text-xs text-muted-foreground">→</span>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Target Namespace <span className="text-destructive">*</span></Label>
              <Select value={targetNs} onValueChange={(v) => v && setTargetNs(v)}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {NAMESPACES.map(ns => (
                    <SelectItem key={ns} value={ns} disabled={ns === sourceNs} className="text-sm font-mono">{ns}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Target table + Schedule */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-xs">
                Target Table <span className="text-destructive">*</span>
                <span className="ml-1 text-muted-foreground font-normal">
                  → iceberg.{targetNs}.
                </span>
              </Label>
              <Input
                placeholder="orders_clean"
                value={targetTable}
                onChange={e => setTargetTable(e.target.value)}
                className="h-8 text-sm font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Schedule</Label>
              <Select value={schedule} onValueChange={(v) => setSchedule(v ?? "")}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue placeholder="Manual only" />
                </SelectTrigger>
                <SelectContent>
                  {SCHEDULES.map(s => (
                    <SelectItem key={s.value} value={s.value} className="text-sm">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* SQL editor */}
          <div className="space-y-1.5">
            <Label className="text-xs">
              SQL <span className="text-destructive">*</span>
              <span className="ml-1 text-muted-foreground font-normal text-[10px]">
                SELECT only — no CREATE TABLE needed
              </span>
            </Label>
            <Textarea
              placeholder={SQL_PLACEHOLDER}
              value={sql}
              onChange={e => setSql(e.target.value)}
              className="font-mono text-xs min-h-[200px] resize-y"
            />
          </div>

          {sourceNs === targetNs && (
            <Alert variant="destructive" className="py-2">
              <AlertCircle className="h-3.5 w-3.5" />
              <AlertDescription className="text-xs">Source and target namespace must differ.</AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive" className="py-2">
              <AlertCircle className="h-3.5 w-3.5" />
              <AlertDescription className="text-xs">{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleClose} disabled={submitting}>Cancel</Button>
          <Button size="sm" onClick={handleSubmit} disabled={!valid || submitting} className="gap-1.5">
            {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Rocket className="h-3.5 w-3.5" />}
            {submitting ? "Deploying…" : editing ? "Update & Redeploy" : "Deploy Transform"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
