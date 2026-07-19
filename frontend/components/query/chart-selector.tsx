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

interface ChartSelectorProps {
  selectedType: ChartType
  onTypeChange: (type: ChartType) => void
}

const chartTypes: { type: ChartType; icon: React.ComponentType<{ className?: string }>; label: string }[] = [
  { type: "table", icon: TableIcon, label: "Table" },
  { type: "line", icon: LineChartIcon, label: "Line" },
  { type: "bar", icon: BarChart3, label: "Bar" },
  { type: "area", icon: AreaChartIcon, label: "Area" },
  { type: "pie", icon: PieChartIcon, label: "Pie" },
]

export function ChartSelector({ selectedType, onTypeChange }: ChartSelectorProps) {
  return (
    <div className="flex items-center gap-1 p-1 bg-muted rounded-lg">
      {chartTypes.map(({ type, icon: Icon, label }) => (
        <Button
          key={type}
          variant={selectedType === type ? "default" : "ghost"}
          size="sm"
          onClick={() => onTypeChange(type)}
          className="gap-2"
        >
          <Icon className="h-4 w-4" />
          {label}
        </Button>
      ))}
    </div>
  )
}
