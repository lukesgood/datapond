/** CPU (millicores) and memory (MiB) as one short cell; "—" when metrics-server gave nothing. */
export function formatUsage(cpuM?: number | null, memMi?: number | null): string {
  if (cpuM == null && memMi == null) return "—"
  const cpu = cpuM == null ? "—" : cpuM >= 1000 ? `${(cpuM / 1000).toFixed(1)} cores` : `${cpuM}m`
  const mem = memMi == null ? "—" : memMi >= 1024 ? `${(memMi / 1024).toFixed(1)} Gi` : `${memMi} Mi`
  return `${cpu} · ${mem}`
}
