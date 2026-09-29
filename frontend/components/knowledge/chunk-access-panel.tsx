"use client"

import { useState } from "react"
import { AlertCircle, Loader2, ShieldAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import {
  isInvalidRule, isRule, ruleError, type StoredChunkRule,
} from "@/lib/chunk-rule"

/** Which chunks of this collection a caller may retrieve.
 *
 *  PUT/DELETE /ai/collections/{name}/chunk-access (backend/app/chunk_access.py).
 *  The current rule arrives with the collection list; `canEdit` is the client-side
 *  guess (owner or admin) and the API's 403 stays the boundary.
 */
export function ChunkAccessPanel({ name, initial, canEdit, onChange }: {
  name: string
  initial: StoredChunkRule
  canEdit: boolean
  onChange: () => void
}) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const [current, setCurrent] = useState<StoredChunkRule>(initial)
  const [key, setKey] = useState(isRule(initial) ? initial.metadata_key : "")
  const [attr, setAttr] = useState(isRule(initial) ? initial.user_attribute : "")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const url = `/api/ai/collections/${encodeURIComponent(name)}/chunk-access`
  const problem = key || attr ? ruleError({ metadata_key: key, user_attribute: attr }) : null

  const save = async () => {
    setBusy(true); setErr(null)
    try {
      const r = await fetch(url, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metadata_key: key, user_attribute: attr }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
      setCurrent(d.chunk_access)
      toast("Chunk access rule saved", "success"); onChange()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save the rule")
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    const ok = await confirm({
      title: "Remove rule",
      message: `Everyone who can read "${name}" will see every chunk again.`,
      destructive: true, confirmText: "Remove",
    })
    if (!ok) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(url, { method: "DELETE" })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`)
      setCurrent(null); setKey(""); setAttr("")
      toast("Chunk access rule removed", "success"); onChange()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not remove the rule")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 pt-3">
      <div className="rounded-lg border px-3 py-2 text-xs">
        {isRule(current) ? (
          <>Retrieval returns only chunks whose <code className="font-mono">{current.metadata_key}</code> matches
            the caller&apos;s <code className="font-mono">{current.user_attribute}</code> attribute.</>
        ) : isInvalidRule(current) ? (
          <span className="text-destructive">This collection has a stored rule that cannot be read, so
            retrieval returns nothing. Save a new rule or remove it.</span>
        ) : (
          <>Everyone who can read this collection sees every chunk.</>
        )}
      </div>

      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        With a rule on, callers without the attribute and chunks without the key are withheld.
        Admins are held to it too.
      </p>

      {canEdit ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Input value={key} onChange={e => setKey(e.target.value)} placeholder="metadata key (e.g. dept)"
                   aria-label="Chunk metadata key" className="h-8 min-w-40 flex-1 text-xs font-mono" />
            <Input value={attr} onChange={e => setAttr(e.target.value)} placeholder="user attribute (e.g. department)"
                   aria-label="User attribute" className="h-8 min-w-40 flex-1 text-xs font-mono" />
            <Button size="sm" onClick={() => void save()} disabled={!key || !attr || !!problem || busy}>
              {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Save
            </Button>
            {current && (
              <Button size="sm" variant="outline" onClick={() => void remove()} disabled={busy}>Remove rule</Button>
            )}
          </div>
          {problem && <p className="text-2xs text-destructive">{problem}</p>}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          The collection&apos;s owner or an administrator can change this rule.
        </p>
      )}

      {err && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />{err}
        </div>
      )}
    </div>
  )
}
