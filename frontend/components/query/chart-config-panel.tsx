"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"

interface ChartConfigPanelProps {
  columns: string[]
  xAxis: string
  yAxis: string
  onXAxisChange: (value: string) => void
  onYAxisChange: (value: string) => void
  showGrid: boolean
  showLegend: boolean
  onShowGridChange: (value: boolean) => void
  onShowLegendChange: (value: boolean) => void
}

export function ChartConfigPanel({
  columns,
  xAxis,
  yAxis,
  onXAxisChange,
  onYAxisChange,
  showGrid,
  showLegend,
  onShowGridChange,
  onShowLegendChange,
}: ChartConfigPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Chart Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* X-Axis Selector */}
        <div className="space-y-2">
          <Label htmlFor="x-axis">X-Axis</Label>
          <Select
            value={xAxis}
            onValueChange={(value) => {
              if (value !== null) {
                onXAxisChange(value)
              }
            }}
          >
            <SelectTrigger id="x-axis">
              <SelectValue placeholder="Select X-axis column" />
            </SelectTrigger>
            <SelectContent>
              {columns.map((col) => (
                <SelectItem key={col} value={col}>
                  {col}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Y-Axis Selector */}
        <div className="space-y-2">
          <Label htmlFor="y-axis">Y-Axis</Label>
          <Select
            value={yAxis}
            onValueChange={(value) => {
              if (value !== null) {
                onYAxisChange(value)
              }
            }}
          >
            <SelectTrigger id="y-axis">
              <SelectValue placeholder="Select Y-axis column" />
            </SelectTrigger>
            <SelectContent>
              {columns.map((col) => (
                <SelectItem key={col} value={col}>
                  {col}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Display Options */}
        <div className="space-y-3 pt-2 border-t">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="show-grid"
              checked={showGrid}
              onCheckedChange={onShowGridChange}
            />
            <Label
              htmlFor="show-grid"
              className="text-sm font-normal cursor-pointer"
            >
              Show Grid
            </Label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="show-legend"
              checked={showLegend}
              onCheckedChange={onShowLegendChange}
            />
            <Label
              htmlFor="show-legend"
              className="text-sm font-normal cursor-pointer"
            >
              Show Legend
            </Label>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
