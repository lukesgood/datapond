"use client"

import { useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { formatDistance } from "date-fns"
import { Loader2, MoreHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { SourceState } from "@/components/ui/source-state"
import { TransformEditor } from "@/components/transforms/transform-editor"
import { useConfirm } from "@/lib/confirm"
import { parseCron } from "@/lib/schedule"
import { readJson, sourceStatus } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import { formFrom, formReading, type SavedTransform, type TransformForm } from "@/lib/transforms"

function LastRun({ t }: { t: SavedTransform }) {
  if (!t.last_run_state) return <span className="text-muted-foreground">Not run yet</span>
  const tone = t.last_run_state === "success" ? "text-[var(--dp-good-text)]"
    : t.last_run_state === "failed" ? "text-destructive" : "text-muted-foreground"
  const word = t.last_run_state === "success" ? "Succeeded" : t.last_run_state === "failed" ? "Failed"
    : t.last_run_state[0].toUpperCase() + t.last_run_state.slice(1)
  return (
    <span className={tone} title={t.last_run_at ? new Date(t.last_run_at).toLocaleString("en-US") : undefined}>
      {word}{t.last_run_at ? ` · ${formatDistance(new Date(t.last_run_at), new Date(), { addSuffix: true })}` : ""}
    </span>
  )
}

/** The Transforms tab: every SQL transform, and the editor for the one in ?edit=
 *  (an id, or "new"). */
export function TransformsTab({ transforms, loading, error, onReload, canWrite }: {
  transforms: SavedTransform[]
  loading: boolean
  error: string | null
  onReload: () => void
  canWrite: boolean
}) {
  const router = useRouter()
  const params = useSearchParams()
  const { toast } = useToast()
  const confirm = useConfirm()
  const edit = canWrite ? params.get("edit") : null
  const [running, setRunning] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<{ id: string; form: TransformForm; dagId: string | null } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const go = (editId: string | null) => {
    const sp = new URLSearchParams(params.toString())
    sp.set("tab", "transforms")
    if (editId) sp.set("edit", editId); else sp.delete("edit")
    router.replace(`/pipelines?${sp.toString()}`)
  }

  // The list carries no SQL; the editor needs the whole row.
  useEffect(() => {
    if (!edit || edit === "new") return
    let cancelled = false
    fetch(`/api/transforms/${encodeURIComponent(edit)}`)
      .then(r => readJson<SavedTransform>(r))
      .then(t => { if (!cancelled) { setLoaded({ id: t.id, form: formFrom(t), dagId: t.dag_id ?? null }); setLoadError(null) } })
      .catch(e => { if (!cancelled) setLoadError(e instanceof Error ? e.message : "failed") })
    return () => { cancelled = true }
  }, [edit])

  const run = async (t: SavedTransform) => {
    setRunning(t.id)
    try {
      await readJson(await fetch(`/api/transforms/${encodeURIComponent(t.id)}/trigger`, { method: "POST" }))
      toast(`Run started: ${t.dag_id}`, "info")
      onReload()
    } catch (e) {
      toast(`Could not start ${t.name}: ${e instanceof Error ? e.message : "failed"}`, "error")
    } finally {
      setRunning(null)
    }
  }

  const remove = async (t: SavedTransform) => {
    if (!(await confirm({
      title: `Delete ${t.name}`,
      message: `Removes the transform and its Airflow job ${t.dag_id ?? ""}. The table it wrote, ${t.target_namespace}.${t.target_table}, stays.`,
      destructive: true, confirmText: "Delete transform",
    }))) return
    try {
      await readJson(await fetch(`/api/transforms/${encodeURIComponent(t.id)}`, { method: "DELETE" }))
      toast(`Deleted ${t.name}`, "success")
      if (edit === t.id) go(null)
      onReload()
    } catch (e) {
      toast(`Could not delete ${t.name}: ${e instanceof Error ? e.message : "failed"}`, "error")
    }
  }

  const status = sourceStatus({ loading, error, empty: transforms.length === 0 })

  return (
    <div className="space-y-5">
      <SourceState status={status} what="transforms" error={error} onRetry={onReload}
        empty={
          <div className="rounded-xl border bg-card px-5 py-10 text-center">
            <p className="text-sm font-medium">No transforms yet</p>
            <p className="mt-1 text-xs text-muted-foreground">A transform is a SELECT that rewrites a refined or serving table on a schedule.</p>
            {canWrite && edit !== "new" && <Button size="sm" className="mt-3" onClick={() => go("new")}>New transform</Button>}
          </div>
        }>
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="bg-muted/40 text-left text-xs text-muted-foreground">
                <th scope="col" className="px-4 py-2 font-medium">Transform</th>
                <th scope="col" className="px-4 py-2 font-medium">Writes</th>
                <th scope="col" className="px-4 py-2 font-medium">Schedule</th>
                <th scope="col" className="px-4 py-2 font-medium">Last run</th>
                <th scope="col" className="px-4 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {transforms.map(t => (
                <tr key={t.id} className={`border-t ${edit === t.id ? "bg-primary/5" : ""}`}>
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{t.name}</div>
                    {t.description && <div className="text-xs text-muted-foreground">{t.description}</div>}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs">{t.target_namespace}.{t.target_table}</td>
                  <td className="px-4 py-2.5 text-xs">{t.schedule ? parseCron(t.schedule) : <span className="text-muted-foreground">Manual</span>}</td>
                  <td className="px-4 py-2.5 text-xs"><LastRun t={t} /></td>
                  <td className="px-4 py-2.5">
                    {canWrite && (
                      <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                        <Button variant="outline" size="sm" disabled={running === t.id} onClick={() => void run(t)}>
                          {running === t.id && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Run now
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => go(t.id)}>Edit</Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger render={<Button variant="ghost" size="sm" aria-label={`More for ${t.name}`} />}>
                            <MoreHorizontal className="h-4 w-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => router.push(`/pipelines/${encodeURIComponent(t.dag_id ?? "")}`)} disabled={!t.dag_id}>
                              Run history and logs
                            </DropdownMenuItem>
                            <DropdownMenuItem className="text-destructive" onClick={() => void remove(t)}>Delete</DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SourceState>

      {edit === "new" && (
        <TransformEditor key={`new:${params.get("from") ?? ""}`} id={null} initial={formReading(params.get("from"))}
                         onSaved={id => { onReload(); go(id) }} onCancel={() => go(null)} />
      )}
      {edit && edit !== "new" && (loadError
        ? <SourceState status="error" what="this transform" error={loadError} onRetry={() => go(edit)}>{null}</SourceState>
        : loaded?.id === edit
          ? <TransformEditor key={edit} id={edit} initial={loaded.form} dagId={loaded.dagId}
                             onSaved={() => onReload()} onCancel={() => go(null)} />
          : <SourceState status="loading" what="this transform">{null}</SourceState>)}
    </div>
  )
}
