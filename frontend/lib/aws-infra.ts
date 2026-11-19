// Infrastructure › AWS and Cost: types for /api/infra/aws and /api/infra/cost, and
// the arithmetic the forms show before anything is saved. The backend owns the
// estimate (app/aws_cost.py); these helpers only preview a change.

export const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"] as const
export type Day = typeof DAYS[number]
export const DAY_LABEL: Record<Day, string> = { MON: "Mon", TUE: "Tue", WED: "Wed", THU: "Thu", FRI: "Fri", SAT: "Sat", SUN: "Sun" }

export const ACU_HOUR = 0.12
export const MONTH_HOURS = 730
export const AURORA_MIN = [0, 0.5, 1, 2] as const
export const AURORA_MAX = [2, 4, 8, 16] as const

export type Schedule = {
  known: boolean
  editable?: boolean
  enabled?: boolean
  days?: Day[]
  start?: string
  stop?: string
  tz?: string
  start_expression?: string
  stop_expression?: string
}

export type AwsSnapshot = {
  account: string | null
  region: string
  read_at: string
  node: {
    instance_id?: string; instance_type?: string; state?: string; zone?: string
    lifecycle?: "spot" | "on-demand"; launched_at?: string | null; volume_gb?: number; volume_type?: string
    hourly_price?: number | null; spot_price_now?: number; on_demand_hourly?: number | null
    cpu_24h?: { at: string; pct: number }[]; cpu_avg_24h?: number | null; cpu_peak_24h?: number | null
  }
  aurora: {
    cluster: string; status?: string; engine_version?: string; min_acu?: number; max_acu?: number
    acu_now?: number | null; acu_peak_24h?: number | null; connections_peak_24h?: number | null; storage_gb?: number | null
  }
  s3: { bucket: string | null; size_gb: number | null; objects: number | null }
  alarms: { name: string; state: string; watches: string; changed_at: string | null }[]
  dashboards: string[]
  schedule: Schedule
  missing: string[]
  errors: string[]
}

export type CostService = { key: string; label: string; mtd: number; forecast: number; how: string }
export type CostDay = { day: string; aurora: number; ec2: number; other: number; forecast: boolean }

export type CostReport = {
  source: "estimate"
  period: { start: string; end: string; days_elapsed: number }
  services: CostService[]
  total: { mtd: number; forecast: number }
  daily: CostDay[]
  savings: {
    aurora_idle_floor: number | null; aurora_min_acu: number | null; spot_vs_on_demand: number | null
    on_demand_hourly: number | null; schedule_saves: number | null; hours_per_week: number
  }
  not_counted: string[]
  actual: { active: boolean; services?: { label: string; mtd: number }[]; total?: number; read_at?: string; missing?: string[] }
  budget: { pct: number; over: boolean; budget: number } | null
  budget_usd: number | null
  missing: string[]
  read_at: string
  aurora: AwsSnapshot["aurora"]
  node: { instance_type?: string; lifecycle?: string; hourly_price?: number | null; on_demand_hourly?: number | null }
  schedule: Schedule
}

export function money(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—"
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

function minutes(t: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(t.trim())
  if (!m) return null
  const h = Number(m[1]), mm = Number(m[2])
  return h < 24 && mm < 60 ? h * 60 + mm : null
}

/** Hours a week the node runs under a schedule; off (24/7) is 168. */
export function weeklyHours(days: readonly string[], start: string, stop: string, enabled = true): number {
  if (!enabled) return 168
  const a = minutes(start), b = minutes(stop)
  if (a == null || b == null || b <= a) return 0
  return Math.round(((b - a) / 60) * days.length * 100) / 100
}

/** What the problem with a schedule draft is, or null. Mirrors the backend's checks. */
export function scheduleProblem(days: readonly string[], start: string, stop: string): string | null {
  if (!days.length) return "Pick at least one day."
  const a = minutes(start), b = minutes(stop)
  if (a == null) return "Start is not a time (HH:MM)."
  if (b == null) return "Stop is not a time (HH:MM)."
  if (b <= a) return "Stop must be later in the day than start."
  return null
}

/** Monthly cost change of moving from `fromHours` to `toHours` a week at an hourly price. */
export function scheduleDelta(fromHours: number, toHours: number, hourly: number | null | undefined): number | null {
  if (hourly == null) return null
  return Math.round(((toHours - fromHours) / 168) * MONTH_HOURS * hourly * 100) / 100
}

/** What Aurora bills a month when idle at a minimum capacity. */
export function auroraIdle(minAcu: number): number {
  return Math.round(minAcu * ACU_HOUR * MONTH_HOURS * 100) / 100
}

export function capacityProblem(min: number, max: number): string | null {
  return min < max ? null : "The maximum must be larger than the minimum."
}

/** The stop time today in the schedule's zone, for "stops today 18:00 KST". */
export function stopsToday(s: Schedule, now: Date = new Date()): string | null {
  if (!s.known || !s.enabled || !s.stop || !s.days?.length) return null
  const tz = s.tz || "UTC"
  const wd = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: tz }).format(now).toUpperCase().slice(0, 3)
  if (!s.days.includes(wd as Day)) return null
  return `${s.stop} ${tzShort(tz)}`
}

export function tzShort(tz: string): string {
  return tz === "Asia/Seoul" ? "KST" : tz === "UTC" ? "UTC" : tz
}

/** Group a list of IAM actions the node role lacks into one sentence. */
export function missingSentence(missing: string[]): string | null {
  if (!missing.length) return null
  const list = missing.length > 4 ? `${missing.slice(0, 4).join(", ")} and ${missing.length - 4} more` : missing.join(", ")
  return `The node role may not call ${list} yet, so those parts are empty. Apply the InfraRead/InfraManage statements in terraform/iam.tf.`
}

export function dayTotal(d: CostDay): number {
  return d.aurora + d.ec2 + d.other
}

/** A round axis top for the cost-per-day chart. */
export function niceMax(values: number[]): number {
  const max = Math.max(0, ...values)
  if (max <= 0) return 1
  const step = max <= 2 ? 0.5 : max <= 5 ? 1 : max <= 20 ? 5 : 10
  return Math.ceil(max / step) * step
}

/** Share of the forecast one service takes, as a whole percent. */
export function share(part: number, total: number): number {
  return total > 0 ? Math.round((part / total) * 100) : 0
}
