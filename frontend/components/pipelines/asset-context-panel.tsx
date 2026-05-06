"use client"

import { useEffect, useState } from "react"
import { X, Database, Table2, ShieldCheck, Clock, Layers, ArrowRight, ArrowLeft } from "lucide-react"
import { AssetNodeData } from "./asset-node"

interface AssetContextPanelProps {
  nodeId: string | null
  nodeData: AssetNodeData | null
  dagId: string
  edges: { source: string; target: string }[]
  allNodes: { id: string; data: AssetNodeData }[]
  onClose: () => void
}

export function AssetContextPanel({ nodeId, nodeData, dagId, edges, allNodes, onClose }: AssetContextPanelProps) {
  const [taskLog, setTaskLog] = useState<string | null>(null)

  useEffect(() => { setTaskLog(null) }, [nodeId])

  if (!nodeId || !nodeData) return null

  const upstream = edges.filter(e => e.target === nodeId).map(e => allNodes.find(n => n.id === e.source)).filter(Boolean)
  const downstream = edges.filter(e => e.source === nodeId).map(e => allNodes.find(n => n.id === e.target)).filter(Boolean)

  const ICON = { source: Database, table: Table2, quality: ShieldCheck }
  const Icon = ICON[nodeData.asset_type] ?? Table2

  return (
    <div className="w-80 h-full border-l bg-background flex flex-col overflow-hidden shrink-0 animate-in slide-in-from-right-4 duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-medium truncate">{nodeId}</span>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted text-muted-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Properties */}
        <section>
          <h4 className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">Properties</h4>
          <div className="space-y-1.5">
            {[
              { label: "Type", value: nodeData.asset_type },
              { label: "Layer", value: nodeData.layer },
              { label: "Mode", value: nodeData.mode ?? "—" },
              { label: "Operator", value: nodeData.operator ?? "—" },
              { label: "Status", value: nodeData.state ?? "pending" },
              { label: "Freshness", value: nodeData.freshness ?? "—" },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-mono text-[11px]">{value}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Upstream */}
        {upstream.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-1">
              <ArrowLeft className="h-3 w-3" /> Upstream ({upstream.length})
            </h4>
            <div className="space-y-1">
              {upstream.map((n) => (
                <div key={n!.id} className="flex items-center gap-2 text-xs bg-muted rounded px-2 py-1.5">
                  <div className={`h-1.5 w-1.5 rounded-full ${
                    n!.data.layer === "bronze" ? "bg-amber-500" : n!.data.layer === "gold" ? "bg-yellow-500" : "bg-slate-400"
                  }`} />
                  <span className="truncate">{n!.id}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Downstream */}
        {downstream.length > 0 && (
          <section>
            <h4 className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2 flex items-center gap-1">
              <ArrowRight className="h-3 w-3" /> Downstream ({downstream.length})
            </h4>
            <div className="space-y-1">
              {downstream.map((n) => (
                <div key={n!.id} className="flex items-center gap-2 text-xs bg-muted rounded px-2 py-1.5">
                  <div className={`h-1.5 w-1.5 rounded-full ${
                    n!.data.layer === "gold" ? "bg-yellow-500" : n!.data.layer === "quality" ? "bg-violet-500" : "bg-slate-400"
                  }`} />
                  <span className="truncate">{n!.id}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Quick actions */}
        <section>
          <h4 className="text-[10px] uppercase tracking-widest text-muted-foreground mb-2">Actions</h4>
          <div className="space-y-1.5">
            <a
              href={`/query?sql=${encodeURIComponent(`SELECT * FROM ${nodeId} LIMIT 100`)}`}
              className="flex items-center gap-2 text-xs bg-muted hover:bg-accent rounded px-3 py-2 transition-colors"
            >
              <Table2 className="h-3 w-3" /> Preview in SQL Lab
            </a>
            <a
              href={`/catalog?table=${nodeId}`}
              className="flex items-center gap-2 text-xs bg-muted hover:bg-accent rounded px-3 py-2 transition-colors"
            >
              <Layers className="h-3 w-3" /> View in Catalog
            </a>
          </div>
        </section>
      </div>
    </div>
  )
}
