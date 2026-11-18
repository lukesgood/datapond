"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { formatDistanceToNow } from "date-fns"
import { FileText, Folder, RefreshCw, Upload } from "lucide-react"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import { usePermissions } from "@/lib/permissions"
import { responseErrorMessage } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorBox } from "@/components/ui/error-box"
import { PageHeader } from "@/components/ui/page-header"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { breadcrumbs, joinKey, looksLikeTable } from "@/lib/storage-path"

interface BucketStat { name: string; object_count: number; total_size_bytes: number; total_size_human: string; error?: string | null }
interface StorageOverview {
  endpoint: string; bucket_count: number; total_object_count: number; total_size_human: string; buckets: BucketStat[]
}
interface S3Object { bucket: string; key: string; size_bytes: number; size_human: string; last_modified: string }
interface Browse { bucket: string; prefix: string; folders: { prefix: string; name: string }[]; objects: S3Object[]; truncated: boolean }

export default function StoragePage() {
  const { toast } = useToast()
  const confirm = useConfirm()
  // Browsing, upload and delete are require_admin on the backend: a table's raw files
  // bypass row and column policies. Fails closed until /api/me/permissions answers.
  const { role, loaded } = usePermissions()
  const isAdmin = role === "admin"
  const [overview, setOverview] = useState<StorageOverview | null>(null)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const [bucket, setBucket] = useState<string | null>(null)
  const [prefix, setPrefix] = useState("")
  const [listing, setListing] = useState<Browse | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [filter, setFilter] = useState("")
  const [selected, setSelected] = useState<S3Object | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [newBucket, setNewBucket] = useState("")
  const fileInput = useRef<HTMLInputElement | null>(null)
  const listSeq = useRef(0)

  const loadOverview = useCallback(async () => {
    try {
      const res = await fetch("/api/storage/overview")
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Could not read object storage"))
      const data: StorageOverview = await res.json()
      setOverview(data); setOverviewError(null)
      setBucket(b => (b && data.buckets.some(x => x.name === b) ? b : data.buckets[0]?.name ?? null))
    } catch (e) { setOverviewError(e instanceof Error ? e.message : "Could not read object storage") }
  }, [])

  const loadList = useCallback(async (b: string, p: string) => {
    const seq = ++listSeq.current
    setLoadingList(true); setListError(null)
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(b)}/browse?prefix=${encodeURIComponent(p)}`)
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Could not list this folder"))
      const data: Browse = await res.json()
      if (seq === listSeq.current) setListing(data)
    } catch (e) {
      if (seq === listSeq.current) { setListing(null); setListError(e instanceof Error ? e.message : "Could not list this folder") }
    } finally { if (seq === listSeq.current) setLoadingList(false) }
  }, [])

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadOverview() }, [loadOverview])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (bucket && isAdmin) void loadList(bucket, prefix)
  }, [bucket, prefix, isAdmin, loadList])

  const go = (p: string) => { setPrefix(p); setFilter(""); setSelected(null) }
  const refresh = async () => { await loadOverview(); if (bucket && isAdmin) await loadList(bucket, prefix) }

  const upload = async (files: FileList | File[]) => {
    if (!bucket) return
    setBusy(true)
    let done = 0
    for (const file of Array.from(files)) {
      try {
        const res = await fetch(`/api/storage/objects/${encodeURIComponent(bucket)}/${joinKey(prefix, file.name).split("/").map(encodeURIComponent).join("/")}`, {
          method: "PUT", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file,
        })
        if (!res.ok) throw new Error(await responseErrorMessage(res, `Could not upload ${file.name}`))
        done++
      } catch (e) { toast(e instanceof Error ? e.message : `Could not upload ${file.name}`, "error") }
    }
    if (done) toast(`Uploaded ${done} file${done === 1 ? "" : "s"} to ${prefix || bucket}`, "success")
    setBusy(false); await refresh()
  }

  const download = async (o: S3Object) => {
    try {
      const res = await fetch(`/api/storage/objects/${encodeURIComponent(o.bucket)}/${o.key.split("/").map(encodeURIComponent).join("/")}`)
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Download failed"))
      const url = URL.createObjectURL(await res.blob())
      const a = document.createElement("a")
      a.href = url; a.download = o.key.split("/").pop() || o.key
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    } catch (e) { toast(e instanceof Error ? e.message : "Download failed", "error") }
  }

  const remove = async (o: S3Object) => {
    if (!(await confirm({ title: "Delete file", message: `Delete ${o.key} from ${o.bucket}? This cannot be undone. Files inside an Iceberg table are refused.`, confirmText: "Delete", destructive: true }))) return
    setBusy(true)
    try {
      const res = await fetch(`/api/storage/objects/${encodeURIComponent(o.bucket)}/${o.key.split("/").map(encodeURIComponent).join("/")}`, { method: "DELETE" })
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Delete failed"))
      toast(`Deleted ${o.key.split("/").pop()}`, "success"); setSelected(null); await refresh()
    } catch (e) { toast(e instanceof Error ? e.message : "Delete failed", "error") }
    finally { setBusy(false) }
  }

  const copyUri = async (o: S3Object) => {
    try { await navigator.clipboard.writeText(`s3://${o.bucket}/${o.key}`); toast("S3 URI copied", "success") }
    catch { toast("Could not copy to the clipboard", "error") }
  }

  const managed = !overview || overview.endpoint === "aws-native"
  const createBucket = async () => {
    const name = newBucket.trim()
    if (!name) return
    setBusy(true)
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(name)}`, { method: "POST" })
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Could not create the bucket"))
      toast(`Bucket ${name} created`, "success"); setNewBucket(""); setBucket(name); go(""); await loadOverview()
    } catch (e) { toast(e instanceof Error ? e.message : "Could not create the bucket", "error") }
    finally { setBusy(false) }
  }
  const deleteBucket = async (name: string) => {
    if (!(await confirm({ title: `Delete bucket ${name}`, message: "Only an empty bucket can be deleted. This cannot be undone.", confirmText: "Delete", destructive: true }))) return
    try {
      const res = await fetch(`/api/storage/buckets/${encodeURIComponent(name)}`, { method: "DELETE" })
      if (!res.ok) throw new Error(await responseErrorMessage(res, "Could not delete the bucket"))
      toast(`Bucket ${name} deleted`, "success"); setBucket(null); go(""); await loadOverview()
    } catch (e) { toast(e instanceof Error ? e.message : "Could not delete the bucket", "error") }
  }

  const storageLabel = !overview ? "Object storage" : overview.endpoint === "aws-native" ? "Amazon S3" : "S3-compatible storage"
  const q = filter.trim().toLowerCase()
  const folders = (listing?.folders ?? []).filter(f => !q || f.name.toLowerCase().includes(q))
  const objects = (listing?.objects ?? []).filter(o => !q || o.key.slice(prefix.length).toLowerCase().includes(q))
  const inTable = looksLikeTable(prefix, listing?.folders.map(f => f.name) ?? [])
  const crumbs = breadcrumbs(prefix)
  const bucketStat = overview?.buckets.find(b => b.name === bucket)

  return (
    <div className="mx-auto max-w-[1400px] flex-1 space-y-5 p-8 pt-6">
      <PageHeader title="Storage"
        description={overview
          ? `${storageLabel} through the S3 API · ${overview.bucket_count} bucket${overview.bucket_count === 1 ? "" : "s"} · ${overview.total_object_count.toLocaleString()} objects · ${overview.total_size_human}`
          : `${storageLabel} through the S3 API`}
        actions={<Button variant="outline" size="sm" onClick={() => void refresh()}><RefreshCw className="mr-1.5 h-3.5 w-3.5" />Refresh</Button>} />

      {overviewError && <ErrorBox msg={overviewError} action={<Button size="sm" variant="outline" onClick={() => void loadOverview()}>Retry</Button>} />}

      {loaded && !isAdmin ? (
        <div className="flex flex-wrap items-start gap-5">
          <section className="min-w-0 flex-[3_1_560px] overflow-hidden rounded-xl border bg-card">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><th scope="col" className="px-4 py-2 font-medium">Bucket</th><th scope="col" className="px-4 py-2 text-right font-medium">Objects</th><th scope="col" className="px-4 py-2 text-right font-medium">Size</th></tr></thead>
              <tbody>
                {(overview?.buckets ?? []).map(b => (
                  <tr key={b.name} className="border-t"><td className="px-4 py-2 font-mono text-xs">{b.name}</td><td className="px-4 py-2 text-right">{b.error ? "—" : b.object_count.toLocaleString()}</td><td className="px-4 py-2 text-right">{b.error ? "—" : b.total_size_human}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <ExplainRail label="About storage">
            <RailSection title="Browsing files needs an administrator">
              Table files read straight from storage skip row policies and column masking, which apply only to governed queries. Query tables from Analytics or Catalog instead.
            </RailSection>
          </ExplainRail>
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <section className="relative min-w-0 flex-[3_1_600px] overflow-hidden rounded-xl border bg-card"
            onDragOver={bucket && isAdmin ? e => { e.preventDefault(); setDragging(true) } : undefined}
            onDragLeave={e => { if (e.currentTarget === e.target) setDragging(false) }}
            onDrop={bucket && isAdmin ? e => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files?.length) void upload(e.dataTransfer.files) } : undefined}>
            {dragging && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-primary bg-primary/5">
                <p className="text-sm font-medium text-primary">Drop to upload into {prefix || bucket}</p>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2.5 border-b px-4 py-3">
              {overview && overview.buckets.length > 0 && (
                <select aria-label="Bucket" className="h-8 rounded-md border bg-background px-2 text-sm" value={bucket ?? ""}
                        onChange={e => { setBucket(e.target.value); go("") }}>
                  {overview.buckets.map(b => <option key={b.name} value={b.name}>{b.name} · {b.error ? "unreadable" : b.total_size_human}</option>)}
                </select>
              )}
              <nav aria-label="Path" className="min-w-0 truncate font-mono text-xs">
                <button className="text-primary hover:underline" onClick={() => go("")}>{bucket ?? "—"}</button>
                {crumbs.map((c, i) => (
                  <span key={c.prefix}> / {i === crumbs.length - 1
                    ? <strong>{c.name}</strong>
                    : <button className="text-primary hover:underline" onClick={() => go(c.prefix)}>{c.name}</button>}</span>
                ))} /
              </nav>
              <span className="ml-auto" />
              <Input aria-label="Filter this folder" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter this folder" className="h-8 w-44" />
              <input ref={fileInput} type="file" multiple className="hidden" onChange={e => { if (e.target.files?.length) void upload(e.target.files); e.target.value = "" }} />
              <Button size="sm" disabled={!bucket || busy} onClick={() => fileInput.current?.click()}><Upload className="mr-1.5 h-3.5 w-3.5" />Upload files</Button>
            </div>
            {!loaded || (!overview && !overviewError) || (loadingList && !listing) ? (
              <div className="space-y-2 p-4">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
            ) : !bucket ? (
              <p className="p-6 text-sm text-muted-foreground">{overviewError ? "Object storage could not be read." : managed ? "No bucket is configured for this deployment." : "No buckets yet. Create one on the right."}</p>
            ) : listError ? (
              <div className="p-4"><ErrorBox msg={listError} action={<Button size="sm" variant="outline" onClick={() => void loadList(bucket, prefix)}>Retry</Button>} /></div>
            ) : folders.length + objects.length === 0 ? (
              <p className="p-6 text-sm text-muted-foreground">{q ? `Nothing in this folder matches “${filter}”.` : "This folder is empty. Upload files or drop them here."}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                    <tr><th scope="col" className="px-4 py-2 font-medium">Name</th><th scope="col" className="px-4 py-2 text-right font-medium">Size</th><th scope="col" className="px-4 py-2 font-medium">Modified</th></tr>
                  </thead>
                  <tbody>
                    {prefix && !q && (
                      <tr className="border-t"><td colSpan={3} className="px-4 py-1.5">
                        <button className="text-xs text-primary hover:underline" onClick={() => go(crumbs.length > 1 ? crumbs[crumbs.length - 2].prefix : "")}>.. up one folder</button>
                      </td></tr>
                    )}
                    {folders.map(f => (
                      <tr key={f.prefix} className="border-t hover:bg-muted/40">
                        <td className="px-4 py-2"><button className="flex items-center gap-2 text-primary hover:underline" onClick={() => go(f.prefix)}><Folder aria-hidden className="h-3.5 w-3.5" />{f.name}/</button></td>
                        <td className="px-4 py-2 text-right text-muted-foreground">—</td><td className="px-4 py-2 text-muted-foreground">—</td>
                      </tr>
                    ))}
                    {objects.map(o => {
                      const on = selected?.key === o.key
                      return (
                        <tr key={o.key} className={`border-t ${on ? "bg-primary/10" : "hover:bg-muted/40"}`}>
                          <td className="px-4 py-2">
                            <button aria-pressed={on} className="flex min-w-0 items-center gap-2 text-left font-mono text-xs" onClick={() => setSelected(on ? null : o)}>
                              <FileText aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /><span className="truncate">{o.key.slice(prefix.length)}</span>
                            </button>
                          </td>
                          <td className="px-4 py-2 text-right tabular-nums">{o.size_human}</td>
                          <td className="px-4 py-2 text-muted-foreground">{formatDistanceToNow(new Date(o.last_modified), { addSuffix: true })}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {listing && (
              <div className="border-t px-4 py-2 text-xs text-muted-foreground">
                {listing.folders.length} folder{listing.folders.length === 1 ? "" : "s"} · {listing.objects.length} file{listing.objects.length === 1 ? "" : "s"} in this folder
                {listing.truncated && " · showing the first 500; filter or open a sub-folder to see the rest"}
              </div>
            )}
          </section>

          <ExplainRail label={selected ? "File details" : "About this folder"}>
            {selected ? (
              <>
                <h3 className="break-all font-mono text-sm font-semibold text-foreground">{selected.key.split("/").pop()}</h3>
                <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
                  <dt className="text-muted-foreground">Size</dt><dd>{selected.size_human}</dd>
                  <dt className="text-muted-foreground">Modified</dt><dd>{new Date(selected.last_modified).toLocaleString()}</dd>
                  <dt className="text-muted-foreground">Key</dt><dd className="break-all font-mono text-xs">{selected.key}</dd>
                  <dt className="text-muted-foreground">S3 URI</dt><dd className="break-all font-mono text-xs">s3://{selected.bucket}/{selected.key}</dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => void download(selected)}>Download</Button>
                  <Button size="sm" variant="outline" onClick={() => void copyUri(selected)}>Copy S3 URI</Button>
                  <Button size="sm" variant="outline" disabled={busy} className="text-destructive" onClick={() => void remove(selected)}>Delete…</Button>
                </div>
                {inTable && <RailAttention title="Inside an Iceberg table">This looks like part of a table. Deleting its files would corrupt it, so the server refuses. Drop the table from Catalog instead.</RailAttention>}
              </>
            ) : (
              <>
                <RailSection title={prefix ? prefix : bucket ?? "Storage"}>
                  {inTable
                    ? "This folder is an Iceberg table: its data and metadata files. Query it from Analytics; drop it from Catalog."
                    : bucketStat && !prefix ? `${bucketStat.object_count.toLocaleString()} objects · ${bucketStat.total_size_human} in this bucket.` : "Pick a file to see its details."}
                </RailSection>
                <RailSection title="Uploads">Files go into the folder you are in. Drop several at once onto the list.</RailSection>
                {inTable && <RailAttention title="Inside an Iceberg table">Deleting files here is refused: it would corrupt the table.</RailAttention>}
                <RailSection title="Buckets">
                  {managed ? "Buckets are managed by Terraform on this profile." : (
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <Input aria-label="New bucket name" value={newBucket} placeholder="my-bucket" className="h-8 font-mono"
                               onChange={e => setNewBucket(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                               onKeyDown={e => { if (e.key === "Enter") void createBucket() }} />
                        <Button size="sm" disabled={busy || !newBucket.trim()} onClick={() => void createBucket()}>Create</Button>
                      </div>
                      <p className="text-xs">Lowercase letters, digits and hyphens.</p>
                      {bucket && !prefix && listing && listing.folders.length + listing.objects.length === 0 && (
                        <Button size="sm" variant="outline" className="text-destructive" onClick={() => void deleteBucket(bucket)}>Delete empty bucket {bucket}…</Button>
                      )}
                    </div>
                  )}
                </RailSection>
              </>
            )}
          </ExplainRail>
        </div>
      )}
    </div>
  )
}
