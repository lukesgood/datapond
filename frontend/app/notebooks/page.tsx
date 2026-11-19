"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { Loader2, MoreHorizontal, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { ErrorBox } from "@/components/ui/error-box"
import { ExplainRail, RailSection } from "@/components/ui/explain-rail"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { PageHeader } from "@/components/ui/page-header"
import { Skeleton } from "@/components/ui/skeleton"
import { SourceState } from "@/components/ui/source-state"
import { supportBadge, supportTier } from "@/lib/capability-support"
import { CapabilityGate, useCapabilities } from "@/lib/capabilities"
import { useConfirm } from "@/lib/confirm"
import {
  ago, jupyterState, kernelLabel, labUrl, sessionFor, sortNotebooks, withIpynb,
  type NotebookRow, type NotebookSort, type Session,
} from "@/lib/notebooks"
import { useHasPermission } from "@/lib/permissions"
import { readJson, sourceStatus } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import { serviceUrls } from "@/lib/urls"

const apiPath = (path: string) => path.split("/").map(encodeURIComponent).join("/")
const TEMPLATES = [
  { id: "python", label: "Python", hint: "pandas and numpy, ready to query" },
  { id: "spark", label: "Spark", hint: "a PySpark session" },
  { id: "blank", label: "Blank", hint: "an empty notebook" },
] as const

type Dialogs =
  | { kind: "new"; template: string }
  | { kind: "rename"; notebook: NotebookRow }
  | null

function NotebooksPageInner() {
  const { toast } = useToast()
  const confirm = useConfirm()
  const caps = useCapabilities()
  const tier = supportTier("notebooks", caps.support ?? {})
  const badge = tier ? supportBadge(tier) : null
  const canWrite = useHasPermission("workbench:write")

  const [notebooks, setNotebooks] = useState<NotebookRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [jupyter, setJupyter] = useState<string | undefined>(undefined)
  const [sessions, setSessions] = useState<Session[] | null>(null)
  const [sessionsError, setSessionsError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [sort, setSort] = useState<NotebookSort>("changed")
  const [busy, setBusy] = useState<string | null>(null)
  const [dialog, setDialog] = useState<Dialogs>(null)
  const [dialogName, setDialogName] = useState("")
  const [dialogError, setDialogError] = useState<string | null>(null)

  // A refresh keeps what is on screen; only the first load shows skeletons.
  const load = useCallback(async () => {
    setLoading(true)
    const [list, services, sess] = await Promise.allSettled([
      fetch("/api/notebooks?recursive=true").then(r => readJson<{ notebooks: NotebookRow[] }>(r)),
      fetch("/api/services").then(r => readJson<{ name: string; status?: string }[]>(r)),
      fetch("/api/notebooks/sessions/list").then(r => readJson<Session[]>(r)),
    ])
    if (list.status === "fulfilled") { setNotebooks(Array.isArray(list.value.notebooks) ? list.value.notebooks : []); setError(null) }
    else setError(list.reason instanceof Error ? list.reason.message : "failed")
    setJupyter(services.status === "fulfilled" ? services.value.find(s => s.name === "jupyterlab")?.status : undefined)
    if (sess.status === "fulfilled") { setSessions(Array.isArray(sess.value) ? sess.value : []); setSessionsError(null) }
    else setSessionsError(sess.reason instanceof Error ? sess.reason.message : "failed")
    setLoading(false)
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(t)
  }, [load])

  const act = async (key: string, run: () => Promise<void>) => {
    setBusy(key)
    try { await run() } catch (e) { toast(e instanceof Error ? e.message : "Failed", "error") } finally { setBusy(null) }
  }

  const openDialog = (d: Dialogs) => {
    setDialog(d); setDialogError(null)
    setDialogName(d?.kind === "rename" ? d.notebook.path : "")
  }

  const submitDialog = async () => {
    if (!dialog || !dialogName.trim()) return
    const path = withIpynb(dialogName)
    setBusy("dialog"); setDialogError(null)
    try {
      if (dialog.kind === "new") {
        await readJson(await fetch("/api/notebooks/from-template", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, template: dialog.template }),
        }))
        toast(`Created ${path}`, "success")
      } else {
        await readJson(await fetch(`/api/notebooks/${apiPath(dialog.notebook.path)}/rename`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ new_path: path }),
        }))
        toast(`Renamed to ${path}`, "success")
      }
      setDialog(null)
      void load()
    } catch (e) {
      // Inside the dialog: an error behind it is an error nobody sees.
      setDialogError(e instanceof Error ? e.message : "Failed")
    } finally {
      setBusy(null)
    }
  }

  const remove = (nb: NotebookRow) => act(`delete:${nb.path}`, async () => {
    if (!(await confirm({ title: `Delete ${nb.name}`, message: `Deletes ${nb.path} from the deployment's notebook storage. This cannot be undone.`, destructive: true, confirmText: "Delete notebook" }))) return
    await readJson(await fetch(`/api/notebooks/${apiPath(nb.path)}`, { method: "DELETE" }))
    toast(`Deleted ${nb.name}`, "success")
    void load()
  })

  const duplicate = (nb: NotebookRow) => act(`dup:${nb.path}`, async () => {
    await readJson(await fetch(`/api/notebooks/${apiPath(nb.path)}/duplicate`, { method: "POST" }))
    toast(`Duplicated ${nb.name}`, "success")
    void load()
  })

  const download = (nb: NotebookRow) => act(`dl:${nb.path}`, async () => {
    const r = await fetch(`/api/notebooks/download?path=${encodeURIComponent(nb.path)}`)
    if (!r.ok) await readJson(r)
    const url = URL.createObjectURL(await r.blob())
    const a = document.createElement("a")
    a.href = url; a.download = nb.name
    document.body.appendChild(a); a.click(); a.remove()
    URL.revokeObjectURL(url)
  })

  const upload = () => {
    const input = document.createElement("input")
    input.type = "file"; input.accept = ".ipynb,application/x-ipynb+json,application/json"
    input.onchange = () => {
      const file = input.files?.[0]
      if (!file) return
      void act("upload", async () => {
        const form = new FormData()
        form.append("file", file); form.append("path", file.name)
        await readJson(await fetch("/api/notebooks/upload", { method: "POST", body: form }))
        toast(`Uploaded ${file.name}`, "success")
        void load()
      })
    }
    input.click()
  }

  const kernelAction = (s: Session, action: "restart" | "stop") => act(`${action}:${s.kernel?.id}`, async () => {
    if (!s.kernel) return
    const name = s.name || s.path
    if (!(await confirm({
      title: action === "stop" ? `Stop ${name}'s kernel` : `Restart ${name}'s kernel`,
      message: action === "stop"
        ? "Its variables are lost and the notebook stays open without a kernel until one is started again."
        : "Its variables are lost; the notebook keeps its cells and outputs.",
      destructive: action === "stop", confirmText: action === "stop" ? "Stop kernel" : "Restart kernel",
    }))) return
    await readJson(await fetch(`/api/notebooks/kernels/${encodeURIComponent(s.kernel.id)}${action === "restart" ? "/restart" : ""}`,
      { method: action === "restart" ? "POST" : "DELETE" }))
    toast(action === "stop" ? "Kernel stopped" : "Kernel restarted", "success")
    // Only the kernel list changes; the notebook list stays where it is.
    try { setSessions(await readJson<Session[]>(await fetch("/api/notebooks/sessions/list"))) } catch { /* next refresh */ }
  })

  const j = jupyterState(jupyter)
  const rows = notebooks ? sortNotebooks(notebooks, sort, query) : []
  const status = sourceStatus({ loading: notebooks === null, error, empty: (notebooks?.length ?? 0) === 0, hasData: notebooks !== null && notebooks.length > 0 })
  const running = (sessions ?? []).filter(s => s.kernel)

  return (
    <div className="mx-auto max-w-[1180px] space-y-5 px-6 py-6">
      <PageHeader
        title="Notebooks"
        description="Jupyter notebooks stored with the deployment. Read them here; edit them in JupyterLab."
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />Refresh
          </Button>
          {canWrite && <Button variant="outline" size="sm" onClick={upload} disabled={busy === "upload"}>
            {busy === "upload" && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Upload
          </Button>}
          <Button variant="outline" size="sm" disabled={!j.canOpen}
                  onClick={() => window.open(serviceUrls.jupyter(), "_blank", "noopener,noreferrer")}>Open JupyterLab</Button>
          {canWrite && <Button size="sm" onClick={() => openDialog({ kind: "new", template: "python" })}>New notebook</Button>}
        </>}>
        {badge && <p className="mt-1 text-xs text-muted-foreground" title={badge.title}>{badge.label} — {badge.title}</p>}
      </PageHeader>

      {notebooks !== null && error && <div role="alert"><ErrorBox msg={`Could not refresh the list: ${error}`} /></div>}

      <div className="flex flex-wrap items-start gap-6">
        <section className="min-w-0 flex-[3_1_560px] overflow-hidden rounded-xl border bg-card">
          <div className="flex flex-wrap items-center gap-2.5 p-3">
            <Input aria-label="Search notebooks" value={query} onChange={e => setQuery(e.target.value)}
                   placeholder={notebooks ? `Search ${notebooks.length} notebook${notebooks.length === 1 ? "" : "s"}` : "Search notebooks"}
                   className="h-8 min-w-0 flex-1" />
            <select aria-label="Sort" value={sort} onChange={e => setSort(e.target.value as NotebookSort)}
                    className="h-8 rounded-md border bg-background px-2 text-sm">
              <option value="changed">Recently changed</option>
              <option value="name">Name</option>
            </select>
          </div>
          <SourceState status={status} what="notebooks" error={error} onRetry={() => void load()}
            loading={<div className="space-y-2 p-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-10" />)}</div>}
            empty={
              <div className="px-5 py-10 text-center">
                <p className="text-sm font-medium">No notebooks yet</p>
                <p className="mt-1 text-xs text-muted-foreground">Start one from a template, upload an .ipynb, or open a query from Analytics as a notebook.</p>
              </div>
            }>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="bg-muted/40 text-left text-xs text-muted-foreground">
                    <th scope="col" className="px-3 py-2 font-medium">Notebook</th>
                    <th scope="col" className="px-3 py-2 font-medium">Kernel</th>
                    <th scope="col" className="px-3 py-2 font-medium">Changed</th>
                    <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr><td colSpan={4} className="px-3 py-6 text-center text-xs text-muted-foreground">No notebook matches “{query}”.</td></tr>
                  )}
                  {rows.map(nb => {
                    const s = sessionFor(nb.path, sessions ?? [])
                    const dir = nb.path.includes("/") ? nb.path.slice(0, nb.path.lastIndexOf("/") + 1) : ""
                    return (
                      <tr key={nb.path} className="border-t">
                        <td className="px-3 py-2">
                          <Link href={`/notebooks/view?path=${encodeURIComponent(nb.path)}`} className="font-semibold text-primary hover:underline">{nb.name}</Link>
                          {dir && <div className="font-mono text-xs text-muted-foreground">{dir}</div>}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {s?.kernel
                            ? <>{kernelLabel(s.kernel.name)} · <span className="text-[var(--dp-good-text)]">{s.kernel.execution_state ?? "running"}</span></>
                            : <span className="text-muted-foreground">not running</span>}
                        </td>
                        <td className="px-3 py-2 text-xs text-muted-foreground" title={nb.last_modified ? new Date(nb.last_modified).toLocaleString() : undefined}>{ago(nb.last_modified)}</td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                            <Button variant="outline" size="sm" disabled={!j.canOpen}
                                    onClick={() => window.open(labUrl(serviceUrls.jupyter(), nb.path), "_blank", "noopener,noreferrer")}>Edit in JupyterLab</Button>
                            <DropdownMenu>
                              <DropdownMenuTrigger render={<Button variant="ghost" size="sm" aria-label={`More for ${nb.name}: rename, duplicate, download, delete`} />}>
                                {busy?.endsWith(`:${nb.path}`) ? <Loader2 className="h-4 w-4 animate-spin" /> : <MoreHorizontal className="h-4 w-4" />}
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem onClick={() => void download(nb)}>Download</DropdownMenuItem>
                                {canWrite && <>
                                  <DropdownMenuItem onClick={() => openDialog({ kind: "rename", notebook: nb })}>Rename</DropdownMenuItem>
                                  <DropdownMenuItem onClick={() => void duplicate(nb)}>Duplicate</DropdownMenuItem>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem className="text-destructive" onClick={() => void remove(nb)}>Delete</DropdownMenuItem>
                                </>}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </SourceState>
        </section>

        <ExplainRail label="JupyterLab">
          <section className="space-y-1.5">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold">JupyterLab</h3>
              <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${j.tone === "good" ? "text-[var(--dp-good-text)]" : j.tone === "bad" ? "text-destructive" : "text-muted-foreground"}`}>
                <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: j.tone === "good" ? "var(--dp-good)" : j.tone === "bad" ? "var(--destructive)" : "var(--muted-foreground)" }} />
                {j.label}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">Opens in its own tab and may ask you to sign in there. DataPond never puts a Jupyter token in a URL.</p>
          </section>

          <RailSection title={`Running kernels${sessions ? ` · ${running.length}` : ""}`}>
            {sessionsError ? <p>Could not read kernels: {sessionsError}</p>
              : sessions === null ? <p>Loading…</p>
              : running.length === 0 ? <p>None. A kernel starts when a notebook is opened in JupyterLab.</p>
              : (
                <ul className="space-y-2">
                  {running.map(s => (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 text-foreground">
                      <span className="min-w-0">
                        <span className="font-medium">{(s.name || s.path).replace(/\.ipynb$/, "")}</span>
                        <span className="text-xs text-muted-foreground">
                          {" "}· {s.kernel?.execution_state ?? "running"}
                          {s.kernel?.last_activity ? ` ${ago(s.kernel.last_activity)}` : ""}
                          {" "}· {s.kernel?.connections ?? 0} connection{s.kernel?.connections === 1 ? "" : "s"}
                        </span>
                      </span>
                      {canWrite && (
                        <span className="flex gap-1.5">
                          <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => void kernelAction(s, "restart")}>Restart</Button>
                          <Button variant="outline" size="sm" disabled={busy !== null} onClick={() => void kernelAction(s, "stop")}>Stop</Button>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
          </RailSection>

          {canWrite && (
            <RailSection title="Start from a template">
              <ul className="space-y-1.5">
                {TEMPLATES.map(t => (
                  <li key={t.id} className="flex items-center justify-between gap-2">
                    <span><span className="text-foreground">{t.label}</span> <span className="text-xs">· {t.hint}</span></span>
                    <Button variant="outline" size="sm" onClick={() => openDialog({ kind: "new", template: t.id })}>Use</Button>
                  </li>
                ))}
              </ul>
            </RailSection>
          )}
        </ExplainRail>
      </div>

      <Dialog open={dialog !== null} onOpenChange={open => { if (!open) setDialog(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialog?.kind === "rename" ? `Rename ${dialog.notebook.name}` : `New ${TEMPLATES.find(t => t.id === (dialog?.kind === "new" ? dialog.template : ""))?.label ?? ""} notebook`}</DialogTitle>
            <DialogDescription>
              {dialog?.kind === "rename" ? "A path moves it into that folder." : "A path like analysis/churn puts it in a folder; .ipynb is added for you."}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-3" onSubmit={e => { e.preventDefault(); void submitDialog() }}>
            {dialog?.kind === "new" && (
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Template">
                {TEMPLATES.map(t => (
                  <button key={t.id} type="button" role="radio" aria-checked={dialog.template === t.id}
                          onClick={() => setDialog({ kind: "new", template: t.id })}
                          className={`h-8 rounded-md border px-3 text-xs ${dialog.template === t.id ? "border-primary bg-primary/10 font-semibold text-primary" : "bg-card"}`}>
                    {t.label}
                  </button>
                ))}
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="nb-path">{dialog?.kind === "rename" ? "New path" : "Name"}</Label>
              <Input id="nb-path" autoFocus value={dialogName} onChange={e => setDialogName(e.target.value)} className="font-mono" />
            </div>
            {dialogError && <div role="alert"><ErrorBox msg={dialogError} /></div>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setDialog(null)}>Cancel</Button>
              <Button type="submit" disabled={!dialogName.trim() || busy === "dialog"}>
                {busy === "dialog" && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}{dialog?.kind === "rename" ? "Rename" : "Create notebook"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default function NotebooksPage() {
  return (
    <CapabilityGate capability="notebooks">
      <NotebooksPageInner />
    </CapabilityGate>
  )
}
