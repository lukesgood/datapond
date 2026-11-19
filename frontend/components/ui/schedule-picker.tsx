"use client"

import { useState } from "react"
import { ChoiceGroup } from "@/components/ui/choice-group"
import { Label } from "@/components/ui/label"
import { FREQ_OPTIONS, HOUR_OPTIONS, buildSchedule, matchCron, parseCron } from "@/lib/schedule"

const MANUAL = "manual"
const CUSTOM = "custom"

/** How often something runs, as one cron string (null = manual). The one picker for
 *  Sources and Transforms: frequency as toggle buttons, the hour only when it
 *  matters. A cron written elsewhere that no button builds stays selected as
 *  "Custom" until another choice replaces it, instead of showing as daily 02:00. */
export function SchedulePicker({ value, onChange, allowManual = true, disabled, id = "schedule" }: {
  value: string | null
  onChange: (cron: string | null) => void
  allowManual?: boolean
  disabled?: boolean
  id?: string
}) {
  const matched = matchCron(value)
  const freqId = value ? (matched?.freqId ?? CUSTOM) : allowManual ? MANUAL : "daily"
  // The hour survives switching to an hourly choice and back.
  const [hour, setHour] = useState(matched?.hour ?? 2)
  const freq = FREQ_OPTIONS.find(f => f.id === freqId)

  const options: { label: string; value: string }[] = [
    ...(allowManual ? [{ label: "Manual", value: MANUAL }] : []),
    ...FREQ_OPTIONS.map(f => ({ label: f.label, value: f.id as string })),
    ...(freqId === CUSTOM ? [{ label: `Custom: ${parseCron(value ?? "")}`, value: CUSTOM }] : []),
  ]

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="space-y-1.5">
        <p className="text-sm font-medium">How often</p>
        <ChoiceGroup label="How often" value={freqId} disabled={disabled} options={options}
                     onChange={v => { if (v !== CUSTOM) onChange(buildSchedule(v, hour)) }} />
      </div>
      {freq?.hasTime && (
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-hour`}>At</Label>
          <select id={`${id}-hour`} value={hour} disabled={disabled}
                  onChange={e => { const h = Number(e.target.value); setHour(h); onChange(buildSchedule(freqId, h)) }}
                  className="h-8 rounded-md border bg-background px-2 text-sm">
            {HOUR_OPTIONS.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
          </select>
        </div>
      )}
    </div>
  )
}
