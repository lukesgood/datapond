"use client"

import { Button } from "@/components/ui/button"
import {
  BarChart3,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  AreaChart as AreaChartIcon,
  Table as TableIcon,
} from "lucide-react"
import { ChartType } from "./chart-renderer"
import type { Availability } from "@/lib/chart-recommend"

interface ChartSelectorProps {
  selectedType: ChartType
  onTypeChange: (type: ChartType) => void
  /** Types that do not fit this result are disabled, with the reason as the tooltip. */
  availability?: Partial<Record<ChartType, Availability>>
}

const chartTypes: { type: ChartType; icon: React.ComponentType<{ className?: string }>; label: string }[] = [
  { type: "table", icon: TableIcon, label: "Table" },
  { type: "line", icon: LineChartIcon, label: "Line" },
  { type: "bar", icon: BarChart3, label: "Bar" },
  { type: "area", icon: AreaChartIcon, label: "Area" },
  { type: "pie", icon: PieChartIcon, label: "Pie" },
]

export function ChartSelector({ selectedType, onTypeChange, availability }: ChartSelectorProps) {
  return (
    <div className="flex items-center gap-1 p-1 bg-muted rounded-lg" role="group" aria-label="Chart type">
      {chartTypes.map(({ type, icon: Icon, label }) => {
        const fit = availability?.[type]
        const off = fit ? !fit.ok : false
        return (
          // A span carries the tooltip: a disabled button receives no pointer events.
          <span key={type} title={off ? fit?.reason : label}>
            <Button
              variant={selectedType === type ? "default" : "ghost"}
              size="sm"
              onClick={() => onTypeChange(type)}
              disabled={off}
              aria-label={off ? `${label} — unavailable: ${fit?.reason}` : label}
              className="gap-2"
            >
              <Icon className="h-4 w-4" />
              {label}
            </Button>
          </span>
        )
      })}
    </div>
  )
}
