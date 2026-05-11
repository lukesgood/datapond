export const FREQ_OPTIONS = [
  { label: "Every 15 min", id: "15min",   buildCron: (_h: number) => "*/15 * * * *",  hasTime: false },
  { label: "Every hour",   id: "hourly",  buildCron: (_h: number) => "0 * * * *",      hasTime: false },
  { label: "Every 6 hours",id: "6h",      buildCron: (_h: number) => "0 */6 * * *",    hasTime: false },
  { label: "Every 12 hours",id: "12h",    buildCron: (_h: number) => "0 */12 * * *",   hasTime: false },
  { label: "Once a day",   id: "daily",   buildCron: (h: number)  => `0 ${h} * * *`,   hasTime: true  },
  { label: "Once a week",  id: "weekly",  buildCron: (h: number)  => `0 ${h} * * 1`,   hasTime: true  },
  { label: "Once a month", id: "monthly", buildCron: (h: number)  => `0 ${h} 1 * *`,   hasTime: true  },
] as const

export const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
  value: i,
  label: i === 0 ? "Midnight" : i === 12 ? "Noon"
    : `${String(i % 12 || 12).padStart(2, "0")}:00 ${i < 12 ? "AM" : "PM"}`,
}))

export function parseCron(cron: string): string {
  if (!cron) return ""
  for (const f of FREQ_OPTIONS) {
    for (let h = 0; h < 24; h++) {
      if (f.buildCron(h) === cron) {
        if (!f.hasTime) return f.label
        const timeLabel = HOUR_OPTIONS.find(o => o.value === h)?.label ?? `${h}:00`
        return `${f.label} · ${timeLabel}`
      }
    }
  }
  const parts = cron.split(" ")
  if (parts.length !== 5) return cron
  const [min, hour, dom, , dow] = parts
  if (min.startsWith("*/")) return `Every ${min.slice(2)} min`
  if (hour === "*") return "Every hour"
  if (dow === "*" && dom === "*") return `Daily ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`
  return cron
}

export function cronToFreqHour(cron: string): { freqId: string; hour: number } {
  for (const f of FREQ_OPTIONS) {
    for (let h = 0; h < 24; h++) {
      if (f.buildCron(h) === cron) return { freqId: f.id, hour: h }
    }
  }
  return { freqId: "daily", hour: 2 }
}

export function nextRun(cron: string): string {
  try {
    const parts = cron.split(" ")
    if (parts.length !== 5) return ""
    const now = new Date()
    const [min, hour] = parts
    if (min.startsWith("*/")) {
      const interval = parseInt(min.slice(2))
      const rem = interval - (now.getMinutes() % interval)
      return `in ${rem}m`
    }
    const next = new Date(now)
    next.setSeconds(0, 0)
    if (min !== "*") {
      next.setMinutes(parseInt(min))
      if (!hour.startsWith("*/") && hour !== "*") {
        next.setHours(parseInt(hour))
        if (next <= now) next.setDate(next.getDate() + 1)
      } else {
        next.setMinutes(parseInt(min))
        if (next <= now) next.setHours(next.getHours() + 1)
      }
    }
    const diff = next.getTime() - now.getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 60) return `in ${mins}m`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `in ${hrs}h`
    return `in ${Math.floor(hrs / 24)}d`
  } catch { return "" }
}
