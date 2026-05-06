"use client"

import { memo } from "react"
import { NodeProps, Handle, Position } from "reactflow"
import { Database, Table2, ShieldCheck, CircleDot } from "lucide-react"

export interface AssetNodeData {
  label: string
  asset_type: "source" | "table" | "quality"
  layer: "bronze" | "silver" | "gold" | "quality"
  operator?: string
  mode?: "full" | "incremental"
  state?: "success" | "failed" | "running" | "stale" | null
  freshness?: string
}

const LAYER_COLORS = {
  bronze: { bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-900", accent: "#d97706" },
  silver: { bg: "bg-slate-50", border: "border-slate-300", text: "text-slate-700", accent: "#64748b" },
  gold: { bg: "bg-yellow-50", border: "border-yellow-400", text: "text-yellow-900", accent: "#ca8a04" },
  quality: { bg: "bg-violet-50", border: "border-violet-300", text: "text-violet-800", accent: "#7c3aed" },
}

const STATE_DOT = {
  success: "bg-emerald-500",
  failed: "bg-red-500",
  running: "bg-blue-500 animate-pulse",
  stale: "bg-amber-500",
}

const ASSET_ICON = {
  source: Database,
  table: Table2,
  quality: ShieldCheck,
}

function AssetNodeComponent({ data, selected }: NodeProps<AssetNodeData>) {
  const layer = LAYER_COLORS[data.layer] ?? LAYER_COLORS.silver
  const Icon = ASSET_ICON[data.asset_type] ?? CircleDot
  const stateDot = data.state ? STATE_DOT[data.state] : null

  return (
    <div className={`
      relative rounded-md border px-2.5 py-1.5 w-36 transition-all
      ${layer.bg} ${layer.border}
      ${selected ? "ring-2 ring-primary/40 shadow-md" : "shadow-sm"}
    `}>
      <Handle
        type="target"
        position={Position.Left}
        className="!w-1.5 !h-1.5 !bg-slate-300 !border-slate-400 !-left-[3px]"
      />

      {/* Single compact row */}
      <div className="flex items-center gap-1.5">
        <Icon className={`h-3 w-3 ${layer.text} shrink-0 opacity-70`} />
        <span className={`text-[11px] font-medium truncate flex-1 ${layer.text}`}>
          {data.label}
        </span>
        {stateDot && (
          <div className={`h-1.5 w-1.5 rounded-full shrink-0 ${stateDot}`} />
        )}
        {data.mode === "incremental" && (
          <span className="text-[8px] text-muted-foreground shrink-0">Δ</span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Right}
        className="!w-1.5 !h-1.5 !bg-slate-300 !border-slate-400 !-right-[3px]"
      />
    </div>
  )
}

export const AssetNode = memo(AssetNodeComponent)
