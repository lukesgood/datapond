"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { ChoiceGroup } from "@/components/ui/choice-group"
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { readJson } from "@/lib/source-state"
import { useToast } from "@/lib/toast"
import {
  AURORA_MAX, AURORA_MIN, DAYS, DAY_LABEL, auroraIdle, capacityProblem, money, scheduleDelta,
  scheduleProblem, tzShort, weeklyHours, type AwsSnapshot, type Day, type Schedule,
} from "@/lib/aws-infra"

async function put(path: string, body: unknown) {
  return readJson(await fetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }))
}

function Card({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

/** Aurora's capacity range — one of the two settings the console changes. */
export function AuroraCapacityCard({ aurora, onSaved }: { aurora: AwsSnapshot["aurora"]; onSaved: () => void }) {
  const { toast } = useToast()
  const curMin = aurora.min_acu ?? null, curMax = aurora.max_acu ?? null
  const [min, setMin] = useState<number | null>(curMin)
  const [max, setMax] = useState<number | null>(curMax)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (curMin == null || curMax == null || min == null || max == null) {
    return <Card title="Aurora capacity"><p className="text-xs text-muted-foreground">Not read yet: the node role cannot describe the cluster.</p></Card>
  }
  const changed = min !== curMin || max !== curMax
  const problem = capacityProblem(min, max)
  const apply = async () => {
    setBusy(true); setError(null)
    try {
      await put("/api/infra/aurora-capacity", { min_acu: min, max_acu: max })
      toast(`Aurora capacity set to ${min}–${max} ACU`, "success")
      setConfirm(false); onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  return (
    <Card title="Aurora capacity" aside={<span className="text-xs text-muted-foreground">now {curMin}–{curMax} ACU</span>}>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <div className="text-xs font-medium">Minimum ACU</div>
          <ChoiceGroup label="Minimum ACU" value={min} onChange={setMin}
                       options={AURORA_MIN.map(v => ({ label: v === 0 ? "0 (pause when idle)" : String(v), value: v }))} />
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-medium">Maximum ACU</div>
          <ChoiceGroup label="Maximum ACU" value={max} onChange={setMax}
                       options={AURORA_MAX.map(v => ({ label: String(v), value: v }))} />
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          At {min} minimum the database costs about {money(auroraIdle(min))} a month idle.
          {min === 0
            ? " It pauses after 5 idle minutes; the first query after a pause waits about 15 s, and the node's own health checks keep it awake during working hours."
            : " 0 pauses it when idle and saves most of that, at the cost of a slow first query."}
        </p>
        {problem && <p className="text-xs text-destructive">{problem}</p>}
        <Button size="sm" disabled={!changed || !!problem} onClick={() => setConfirm(true)}>Apply…</Button>
      </div>
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Change Aurora to {min}–{max} ACU?</AlertDialogTitle>
            <AlertDialogDescription>
              Applied immediately to {aurora.cluster}; connections stay open. Idle cost goes from {money(auroraIdle(curMin))} to {money(auroraIdle(min))} a month.
              Terraform keeps this value (it ignores later changes to the range).
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button disabled={busy} onClick={() => { void apply() }}>
              {busy ? "Applying…" : "Apply"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

/** The node's start/stop schedule — the other setting the console changes. */
export function ScheduleCard({ schedule, hourly, onSaved }: { schedule: Schedule; hourly: number | null | undefined; onSaved: () => void }) {
  const { toast } = useToast()
  const [days, setDays] = useState<Day[]>(schedule.days ?? ["MON", "TUE", "WED", "THU", "FRI"])
  const [start, setStart] = useState(schedule.start ?? "07:30")
  const [stop, setStop] = useState(schedule.stop ?? "18:00")
  const [confirm, setConfirm] = useState<null | "save" | "always" | "resume">(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!schedule.known) {
    return <Card title="When the node runs"><p className="text-xs text-muted-foreground">Not read yet: the node role cannot read the start/stop schedules.</p></Card>
  }
  if (!schedule.editable) {
    return (
      <Card title="When the node runs">
        <p className="text-xs text-muted-foreground">The schedules use expressions this form cannot build, so they are shown as written:</p>
        <p className="mt-2 font-mono text-xs">start {schedule.start_expression}<br />stop {schedule.stop_expression}</p>
      </Card>
    )
  }
  const tz = tzShort(schedule.tz || "UTC")
  const nowHours = weeklyHours(schedule.days ?? [], schedule.start ?? "", schedule.stop ?? "", schedule.enabled)
  const draftHours = weeklyHours(days, start, stop)
  const problem = scheduleProblem(days, start, stop)
  const changed = days.join() !== (schedule.days ?? []).join() || start !== schedule.start || stop !== schedule.stop
  const delta = scheduleDelta(nowHours, confirm === "always" ? 168 : draftHours, hourly)

  const save = async (enabled: boolean) => {
    setBusy(true); setError(null)
    try {
      await put("/api/infra/schedule", { days, start, stop, enabled })
      toast(enabled ? "Node schedule saved" : "Node now runs 24/7", "success")
      setConfirm(null); onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  const toggle = (d: Day) => setDays(cur => cur.includes(d) ? cur.filter(x => x !== d) : DAYS.filter(x => x === d || cur.includes(x)))

  return (
    <Card title="When the node runs" aside={!schedule.enabled && <span className="text-xs font-medium text-[var(--dp-warn-text)]">Running 24/7</span>}>
      <div className="space-y-3">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Days">
          {DAYS.map(d => {
            const on = days.includes(d)
            return (
              <button key={d} type="button" aria-pressed={on} onClick={() => toggle(d)}
                      className={`h-8 w-10 rounded-md border text-xs ${on ? "border-primary bg-primary/10 font-semibold text-primary" : "bg-card hover:border-primary/50"}`}>
                {DAY_LABEL[d]}
              </button>
            )
          })}
        </div>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1 text-xs font-medium">Start
            <input type="time" value={start} onChange={e => setStart(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm font-normal" />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium">Stop
            <input type="time" value={stop} onChange={e => setStop(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-sm font-normal" />
          </label>
          <span className="pb-2 text-xs text-muted-foreground">{tz}</span>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {draftHours} h a week.{" "}
          {hourly != null && <>Running all the time would add about {money(scheduleDelta(draftHours, 168, hourly), 0)} a month. </>}
          Nothing in DataPond answers while it is stopped: agents, syncs and transforms wait.
        </p>
        {problem && <p className="text-xs text-destructive">{problem}</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={!changed || !!problem} onClick={() => setConfirm("save")}>Save schedule</Button>
          {schedule.enabled
            ? <Button size="sm" variant="outline" onClick={() => setConfirm("always")}>Run 24/7…</Button>
            : <Button size="sm" variant="outline" disabled={!!problem} onClick={() => setConfirm("resume")}>Resume schedule…</Button>}
        </div>
      </div>
      <AlertDialog open={confirm != null} onOpenChange={(o) => { if (!o) setConfirm(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm === "always" ? "Keep the node running all the time?" : `Run the node ${days.map(d => DAY_LABEL[d]).join(", ")} ${start}–${stop} ${tz}?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === "always"
                ? "Both start and stop schedules are switched off; the node stays up until you resume them."
                : "Both EventBridge schedules are rewritten. If the node is outside these hours now, it stops at the next stop time, which takes this console offline with it."}
              {delta != null && delta !== 0 && <> About {delta > 0 ? "+" : "−"}{money(Math.abs(delta), 0)} a month.</>}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <Button disabled={busy} onClick={() => { void save(confirm !== "always") }}>
              {busy ? "Saving…" : confirm === "always" ? "Run 24/7" : "Save schedule"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}
