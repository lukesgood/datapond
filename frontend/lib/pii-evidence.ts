/** Personal-data evidence (design thinking D1): GET /api/governance/pii-evidence rows turned
 *  into the cells the Governance table shows. Evidence never carries raw values. */

export type EvidenceColumn = { column: string; masked_at_sync: boolean; sampled: number; raw_found: number; types: string[] }
export type EvidenceTable = {
  table: string
  source: string
  source_table: string
  last_run_at: string | null
  status: "ok" | "raw_found" | "unverified"
  error?: string | null
  raw_columns: string[]
  columns: EvidenceColumn[]
}
export type PiiEvidence = {
  summary: { tables: number; ok: number; raw_found: number; unverified: number }
  tables: EvidenceTable[]
  sample_rows: number
  checked_at: string
}

export type EvidenceResult = { tone: "good" | "warn" | "muted"; text: string }

/** The result cell: "No raw values in sample", "Raw values in: phone (phone_kr)", "Not verified". */
export function evidenceResult(t: EvidenceTable): EvidenceResult {
  if (t.status === "ok") return { tone: "good", text: "No raw values in sample ✓" }
  if (t.status === "raw_found") {
    const parts = t.raw_columns.map((c) => {
      const types = t.columns.find((x) => x.column === c)?.types ?? []
      return types.length ? `${c} (${types.join(", ")})` : c
    })
    return { tone: "warn", text: `Raw values in: ${parts.join(", ")} ⚠` }
  }
  return { tone: "muted", text: t.error ? `Not verified: ${t.error}` : "Not verified" }
}

export function maskedColumns(t: EvidenceTable): string[] {
  return t.columns.filter((c) => c.masked_at_sync).map((c) => c.column)
}

export function parsePiiEvidence(raw: unknown): PiiEvidence | null {
  if (!raw || typeof raw !== "object") return null
  const r = raw as Partial<PiiEvidence>
  if (!r.summary || !Array.isArray(r.tables)) return null
  return {
    summary: r.summary, sample_rows: r.sample_rows ?? 0, checked_at: r.checked_at ?? "",
    tables: r.tables.map((t) => ({ ...t, raw_columns: t.raw_columns ?? [], columns: t.columns ?? [] })),
  }
}
