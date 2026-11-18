"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ExplainRail, RailSection } from "@/components/ui/explain-rail"
import { useConfirm } from "@/lib/confirm"
import { useToast } from "@/lib/toast"
import { responseErrorMessage } from "@/lib/auth"
import { edgeApproved, fieldError, joinCandidatePayload, type CatalogEntry, type RelationshipEdge } from "@/lib/metrics"
import type { Join } from "./metric-editor"

const on = (j: Join) => j.on_columns.map(p => p.join(" = ")).join(", ")

export function JoinsPanel({ canApprove, catalogs }: { canApprove: boolean; catalogs: CatalogEntry[] }) {
  const { toast } = useToast()
  const confirm = useConfirm()
  // Approved joins load on their own: the candidates read query history and column names
  // across the catalog, which is slow, and must not hold the approved list back.
  const [joins, setJoins] = useState<Join[] | null>(null)
  const [joinsError, setJoinsError] = useState(false)
  const [edges, setEdges] = useState<RelationshipEdge[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const loadJoins = useCallback(async () => {
    try {
      const r = await fetch("/api/semantic/joins")
      if (!r.ok) throw new Error()
      setJoins((await r.json()).joins ?? []); setJoinsError(false)
    } catch { setJoins([]); setJoinsError(true) }
  }, [])
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadJoins() }, [loadJoins])
  useEffect(() => {
    fetch("/api/catalog/relationships").then(r => (r.ok ? r.json() : { edges: [] }))
      .then(g => setEdges(g.edges ?? [])).catch(() => setEdges([]))
  }, [])
  const candidates = (edges ?? []).filter(e => e.joins?.length && !edgeApproved(e, joins ?? [], catalogs))

  const approve = async (e: RelationshipEdge, reversed: boolean) => {
    const body = joinCandidatePayload(e, catalogs, reversed)
    if (!body) return
    const key = `${e.source}-${e.target}-${reversed}`
    setBusy(key)
    try {
      const res = await fetch("/api/semantic/joins", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      })
      if (res.ok) { toast("Join approved", "success"); await loadJoins(); return }
      const data = await res.json().catch(() => ({}))
      toast(fieldError(data.detail)?.message ?? (typeof data.detail === "string" ? data.detail : "Approval failed"), "error")
    } catch (err) { toast(err instanceof Error ? err.message : "Approval failed", "error") }
    finally { setBusy(null) }
  }

  const revoke = async (j: Join) => {
    if (!(await confirm({
      title: `Revoke ${j.from_table} → ${j.to_table}`,
      message: "New metric versions can no longer split by this table's columns. Versions already saved keep their copy of the join, so past results still resolve. A join that a live metric uses cannot be revoked.",
      confirmText: "Revoke", destructive: true,
    }))) return
    setBusy(`revoke-${j.id}`)
    try {
      const res = await fetch(`/api/semantic/joins/${j.id}`, { method: "DELETE" })
      if (!res.ok) { toast(await responseErrorMessage(res, "Revoke failed"), "error"); return }
      toast("Join revoked", "success"); await loadJoins()
    } catch (err) { toast(err instanceof Error ? err.message : "Revoke failed", "error") }
    finally { setBusy(null) }
  }

  return (
    <div className="flex flex-wrap items-start gap-5">
      <div className="min-w-0 flex-[3_1_560px] space-y-5">
        <section className="overflow-hidden rounded-xl border bg-card">
          <h2 className="border-b px-4 py-3 text-sm font-semibold">Approved joins {joins && <span className="font-normal text-muted-foreground">{joins.length}</span>}</h2>
          {joins === null ? <p className="p-4 text-sm text-muted-foreground">Loading…</p>
            : joinsError ? <p className="p-4 text-sm text-destructive">Could not load approved joins. <button className="underline" onClick={() => void loadJoins()}>Retry</button></p>
            : joins.length === 0 ? <p className="p-4 text-sm text-muted-foreground">None yet. Approve a candidate below to let metrics split by another table&apos;s columns.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                  <tr><th scope="col" className="px-4 py-2 font-medium">From → to</th><th scope="col" className="px-2 py-2 font-medium">On</th><th scope="col" className="px-2 py-2 font-medium">Approved by</th>{canApprove && <th scope="col"><span className="sr-only">Actions</span></th>}</tr>
                </thead>
                <tbody>
                  {joins.map(j => (
                    <tr key={j.id} className="border-t">
                      <td className="px-4 py-2 font-mono text-xs">{j.from_table} → {j.to_table}<div className="font-sans text-muted-foreground">{j.catalog}</div></td>
                      <td className="px-2 py-2 font-mono text-xs">{on(j)}</td>
                      <td className="px-2 py-2 text-xs">{j.approved_by_name ?? "—"} <span className="text-muted-foreground">({j.source})</span></td>
                      {canApprove && <td className="px-2 py-2 text-right"><Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void revoke(j)}>Revoke…</Button></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section className="overflow-hidden rounded-xl border bg-card">
          <h2 className="border-b px-4 py-3 text-sm font-semibold">Candidates</h2>
          {edges === null ? <p className="p-4 text-sm text-muted-foreground">Reading query history and column names…</p>
            : candidates.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No new candidates.</p> : (
            <ul className="divide-y">
              {candidates.map(e => (
                <li key={`${e.source}-${e.target}`} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                  <span className="font-mono text-xs">{e.source} → {e.target} on {e.joins![0].left_column} = {e.joins![0].right_column}{" "}
                    <Badge variant="outline">{e.evidence === "observed" ? `history ×${e.count}` : "naming"}</Badge></span>
                  {canApprove && (
                    <span className="flex shrink-0 gap-1">
                      <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => void approve(e, false)}>Approve</Button>
                      <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => void approve(e, true)}>Approve reversed</Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <ExplainRail label="About joins">
        <RailSection title="What a join does">
          A metric dimension can use a column of another table only through an approved join. Agents never invent joins.
        </RailSection>
        <RailSection title="Where candidates come from">
          Query history (joins people actually ran) and column naming (<span className="font-mono">customer_id</span> → <span className="font-mono">customers.id</span>).
        </RailSection>
        <RailSection title="When you approve">
          The target key is checked unique, so a join never multiplies rows. &ldquo;Approve reversed&rdquo; approves the other direction.
          {!canApprove && <p className="mt-1">Only an administrator approves or revokes joins.</p>}
        </RailSection>
        <RailSection title="When you revoke">
          Refused while a live metric uses the join. Retire that metric, or save a version without the dimension, first.
        </RailSection>
      </ExplainRail>
    </div>
  )
}
