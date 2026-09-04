"use client"

import { useState } from "react"
import { AlertTriangle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { canConfirm } from "@/lib/destructive-card-state"
import { genericPreviewEntries } from "@/lib/preview-render"

type Dependent = { kind: string; name: string; effect: string }
type Dependents = { subject?: string; items?: Dependent[]; not_checked?: string[] }
type Pending = {
  id: string
  label: string
  preview?: Record<string, unknown> | null
}

/** The card for a change that cannot be undone from what the product still holds.
 *
 *  Four things a plain approval does not do: it shows what is actually being changed
 *  — not just the key or id the person typed to confirm, but the value it is being
 *  set to (Critical 3: `settings.set_model_config` let someone type "ai.litellm_url"
 *  and confirm without ever being shown the URL it was about to become) — it names
 *  what else changes, it makes the person type the target, and it says plainly when
 *  the blast radius could not be worked out. That last one matters most — an empty
 *  list reads as "nothing else is affected", so a list that was never computed must
 *  not look like one.
 *
 *  The preview content itself is rendered the same generic way `PreviewBody` (in
 *  assistant-panel.tsx) renders a reversible action's card: `summary` as the lead
 *  sentence when present, everything else as a label/value list via
 *  `genericPreviewEntries` — see that module's docstring for why a fixed key list
 *  does not work here.
 *
 *  `preview.dependents` carries three states, not two, and this card renders each one
 *  differently:
 *
 *   - an object with `items`: something depends on this — list it.
 *   - an object with empty `items` and empty `not_checked`: the check ran and found
 *     nothing. Safe to read as "nothing else depends on this".
 *   - `null` (no dependents callable was registered for this action, per Task 3): the
 *     check never ran at all. Rendered as its own warning line, on its own, and never
 *     folded into the "found nothing" case above — an uncomputed list is not evidence
 *     of an empty one.
 */
export function DestructiveCard({ pending, onApprove, onDismiss, busy }: {
  pending: Pending
  onApprove: (typedTarget: string) => void
  onDismiss: () => void
  busy: boolean
}) {
  const [typed, setTyped] = useState("")
  const preview = pending.preview ?? {}
  const target = typeof preview.target === "string" ? preview.target : ""
  // Any value that isn't a genuine dependents object — undefined, or anything not an
  // object — is treated the same as an explicit null: the check did not run.
  const rawDependents = preview.dependents
  const dependents: Dependents | null =
    rawDependents && typeof rawDependents === "object" ? (rawDependents as Dependents) : null
  const items = dependents?.items ?? []
  const notChecked = dependents?.not_checked ?? []
  const previewSummary = typeof preview.summary === "string" ? preview.summary : ""
  // A destructive action's own target_field (e.g. settings.set_model_config's "key",
  // governance's "policy_id") is not one of genericPreviewEntries' known keys, so
  // without this it would show twice — once here, once as the typed-confirmation
  // label below. Dropped by value, not by a hard-coded field name per action, since
  // this card does not know which field a given action names as its target.
  const previewEntries = genericPreviewEntries(preview)
    .filter(e => !(target && preview[e.key] === target))

  return (
    <div className="rounded-lg border border-[var(--dp-bad)]/40 bg-[var(--dp-bad)]/5 p-3">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <AlertTriangle className="h-3.5 w-3.5 text-[var(--dp-bad)]" />
        {pending.label}
      </p>

      {previewSummary && <p className="mt-1.5 text-[11px]">{previewSummary}</p>}
      {previewEntries.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[11px] text-muted-foreground">
          {previewEntries.map(e => (
            <li key={e.key}>{e.label}: <span className="font-mono">{e.value}</span></li>
          ))}
        </ul>
      )}

      {dependents === null ? (
        <p className="mt-2 text-[11px] text-[var(--dp-warn)]">
          What else depends on this could not be checked. Proceed carefully.
        </p>
      ) : (
        <>
          {items.length > 0 && (
            <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
              {items.map((d, i) => (
                <li key={i}><span className="font-medium">{d.name}</span> — {d.effect}</li>
              ))}
            </ul>
          )}
          {items.length === 0 && notChecked.length === 0 && (
            <p className="mt-2 text-[11px] text-muted-foreground">Nothing else depends on this.</p>
          )}
          {notChecked.length > 0 && (
            <ul className="mt-2 space-y-1 text-[11px] text-[var(--dp-warn)]">
              {notChecked.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
        </>
      )}

      <label className="mt-3 block text-[11px] text-muted-foreground">
        Type <span className="font-mono font-medium text-foreground">{target}</span> to confirm
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          className="mt-1 w-full rounded-md border bg-background px-2 py-1 font-mono text-xs"
          autoComplete="off"
        />
      </label>

      <div className="mt-2.5 flex gap-2">
        <Button size="sm" className="h-7 text-xs" disabled={busy || !canConfirm(typed, target)}
                onClick={() => onApprove(typed)}>
          Confirm
        </Button>
        <Button size="sm" variant="ghost" className="h-7 text-xs" disabled={busy}
                onClick={onDismiss}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
