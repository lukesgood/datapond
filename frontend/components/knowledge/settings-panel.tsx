"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { ExplainRail, RailAttention, RailSection } from "@/components/ui/explain-rail"
import { ChunkAccessPanel } from "@/components/knowledge/chunk-access-panel"
import { useToast } from "@/lib/toast"
import { useConfirm } from "@/lib/confirm"
import type { StoredChunkRule } from "@/lib/chunk-rule"
import {
  effectivePii, lowersPii, lowersSensitivity, piiReason, PII_TEXT, SENSITIVITIES, SENSITIVITY_TEXT,
  type PiiMode, type Sensitivity,
} from "@/lib/collection-protection"

type Preset = { name: string; chunk_size: number; chunk_overlap: number; label: string; hint: string }

export interface SettingsCollection {
  name: string
  description: string | null
  pii_mode?: PiiMode | null
  sensitivity?: Sensitivity | null
  chunk_access?: StoredChunkRule
}

/** Everything about a collection that is a setting, in one place: it was spread over
 *  Composition (description), the create dialog only (split), Chunk access, and
 *  nowhere at all (PII mode, sensitivity — SQL only). Controls on the left; on the
 *  right, what the choices add up to. */
export function SettingsPanel({ c, piiDefault, canEdit, canLower, onChange, onDeleted }: {
  c: SettingsCollection
  piiDefault: PiiMode
  canEdit: boolean
  /** governance:write — lowering PII mode or sensitivity needs it (the API agrees). */
  canLower: boolean
  onChange: () => void
  onDeleted: () => void
}) {
  const { toast } = useToast()
  const confirm = useConfirm()
  const savedPii = c.pii_mode ?? null
  const savedLabel = c.sensitivity ?? null
  const [description, setDescription] = useState(c.description ?? "")
  const [pii, setPii] = useState<PiiMode | null>(savedPii)
  const [label, setLabel] = useState<Sensitivity | null>(savedLabel)
  const [presets, setPresets] = useState<Preset[]>([])
  const [savedPreset, setSavedPreset] = useState<string | null>(null)
  const [preset, setPreset] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetch("/api/ai/chunk-presets").then(r => (r.ok ? r.json() : null)),
      fetch(`/api/ai/collections/${encodeURIComponent(c.name)}/composition`).then(r => (r.ok ? r.json() : null)),
    ]).then(([p, comp]) => {
      if (cancelled) return
      setPresets(p?.presets ?? [])
      const cur = comp?.chunk_preset ?? p?.default ?? null
      setSavedPreset(cur); setPreset(cur)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [c.name])

  const body: Record<string, unknown> = {}
  if (description.trim() !== (c.description ?? "").trim()) body.description = description.trim()
  if (pii !== savedPii) body.pii_mode = pii
  if (label !== savedLabel) body.sensitivity = label
  if (preset && preset !== savedPreset) body.chunk_preset = preset
  const dirty = Object.keys(body).length > 0
  const lowering = (pii !== savedPii && lowersPii(savedPii, pii)) || (label !== savedLabel && lowersSensitivity(savedLabel, label))
  const blocked = lowering && !canLower

  const save = async () => {
    if (!dirty || busy || blocked) return
    setBusy(true); setErr(null)
    try {
      const r = await fetch(`/api/ai/collections/${encodeURIComponent(c.name)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setErr(typeof d.detail === "string" ? d.detail : `Could not save (HTTP ${r.status})`)
        return
      }
      toast("Collection settings saved", "success")
      if (body.chunk_preset) setSavedPreset(preset)
      onChange()
    } finally { setBusy(false) }
  }

  const reset = () => { setDescription(c.description ?? ""); setPii(savedPii); setLabel(savedLabel); setPreset(savedPreset); setErr(null) }

  const remove = async () => {
    if (!(await confirm({
      title: `Delete ${c.name}?`,
      message: "Every chunk and its schedule are deleted, and people and agents lose access. This cannot be undone.",
      destructive: true, confirmText: "Delete collection",
    }))) return
    const r = await fetch(`/api/ai/collections/${encodeURIComponent(c.name)}`, { method: "DELETE" })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      toast(typeof d.detail === "string" ? d.detail : `Could not delete (HTTP ${r.status})`, "error")
      return
    }
    toast(`Collection "${c.name}" deleted`, "success")
    onDeleted()
  }

  const eff = effectivePii(piiDefault, pii, label)
  const reason = piiReason(piiDefault, pii, label)
  const lowerTitle = canLower ? undefined : "Lowering needs governance:write"
  const piiChoices: { label: string; value: PiiMode | null }[] = [
    { label: `Inherit (${piiDefault})`, value: null },
    { label: "off", value: "off" },
    { label: "mask", value: "mask" },
    { label: "block", value: "block" },
  ]
  const piiOptions = piiChoices.map(o => {
    const no = !canLower && lowersPii(savedPii, o.value)
    return { ...o, disabled: no, title: no ? lowerTitle : undefined }
  })
  const labelOptions = [{ label: "No label", value: null as Sensitivity | null }, ...SENSITIVITIES.map(s => ({ label: s, value: s as Sensitivity | null }))]
    .map(o => ({ ...o, disabled: !canLower && lowersSensitivity(savedLabel, o.value), title: !canLower && lowersSensitivity(savedLabel, o.value) ? lowerTitle : undefined }))
  const current = presets.find(p => p.name === preset)

  return (
    <div className="flex flex-wrap items-start gap-5 pt-3">
      <div className="min-w-0 flex-[3_1_380px] space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor="kc-desc">Description</Label>
          <Input id="kc-desc" value={description} onChange={e => setDescription(e.target.value)} disabled={!canEdit}
                 placeholder="What this collection holds" />
        </div>
        <div className="space-y-2 border-t pt-4">
          <Label>Personal data in answers</Label>
          <ChoiceGroup label="PII mode" options={piiOptions} value={pii} onChange={setPii} disabled={!canEdit} />
        </div>
        <div className="space-y-2 border-t pt-4">
          <Label>Sensitivity</Label>
          <ChoiceGroup label="Sensitivity" options={labelOptions} value={label} onChange={setLabel} disabled={!canEdit} />
        </div>
        <div className="space-y-1.5 border-t pt-4">
          <Label htmlFor="kc-split">How new documents are split</Label>
          <select id="kc-split" value={preset ?? ""} onChange={e => setPreset(e.target.value)} disabled={!canEdit || presets.length === 0}
                  className="h-9 w-full max-w-md rounded-md border bg-background px-2 text-sm">
            {presets.map(p => (
              <option key={p.name} value={p.name}>{p.label} — {p.chunk_size.toLocaleString()} characters, {p.chunk_overlap} overlap</option>
            ))}
          </select>
        </div>
        {canEdit && (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={save} disabled={!dirty || busy || blocked}>
              {busy && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}Save settings
            </Button>
            <Button size="sm" variant="ghost" onClick={reset} disabled={!dirty || busy}>Undo changes</Button>
            {err && <span role="alert" className="text-xs text-destructive">{err}</span>}
          </div>
        )}

        <div className="space-y-2 border-t pt-4">
          <Label>Which chunks each caller sees</Label>
          <ChunkAccessPanel name={c.name} initial={c.chunk_access ?? null} canEdit={canEdit} onChange={onChange} />
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 p-3">
            <div>
              <p className="text-sm font-medium text-destructive">Delete collection</p>
              <p className="text-xs text-muted-foreground">Its chunks and schedule go with it. Cannot be undone.</p>
            </div>
            <Button size="sm" variant="outline" className="border-destructive/40 text-destructive" onClick={remove}>Delete…</Button>
          </div>
        )}
      </div>

      <ExplainRail label="What these settings do">
        <RailSection title={`Applies: ${eff}${reason ? ` — ${reason}` : ""}`}>
          {PII_TEXT[eff]} A caller held to a stricter mode still gets theirs.
        </RailSection>
        <RailSection title={label ? `Label: ${label}` : "No label"}>
          {label ? SENSITIVITY_TEXT[label] : "Nothing beyond the PII mode and the deployment's egress policy."}
        </RailSection>
        {current && (
          <RailSection title={`Split: ${current.label}`}>
            For {current.hint}. Applies to what you ingest next; chunks already stored keep their split.
          </RailSection>
        )}
        {blocked && (
          <RailAttention title="This lowers protection" tone="bad">
            Lowering a collection&apos;s PII mode or sensitivity needs governance:write. Raising it is always allowed.
          </RailAttention>
        )}
        {!blocked && lowering && (
          <RailAttention title="This lowers protection">
            More personal data may reach the model, or leave the deployment, once you save.
          </RailAttention>
        )}
        {label === "restricted" && savedLabel !== "restricted" && (
          <RailAttention title="Restricted needs a local model">
            Ingest and answers only use models running inside the deployment. Without one, they fail.
          </RailAttention>
        )}
        {!canEdit && <p className="text-xs text-muted-foreground">Read-only: the owner, an editor or an administrator can change these.</p>}
      </ExplainRail>
    </div>
  )
}
