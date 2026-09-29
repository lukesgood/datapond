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
import { AGGREGATES, AGGREGATE_LABEL, MAX_SERIES, type Aggregate, type ChartType } from "@/lib/chart-data"
import type { Availability } from "@/lib/chart-recommend"

interface ChartConfigPanelProps {
  columns: string[]
  chartType: ChartType
  /** Columns that can sit on each axis; all columns when omitted. */
  xOptions?: string[]
  yOptions?: string[]
  colorOptions?: string[]
  xAxis: string
  yAxes: string[]
  /** "" for none. */
  colorBy: string
  onXAxisChange: (value: string) => void
  onYAxesChange: (value: string[]) => void
  onColorByChange: (value: string) => void
  stacked: boolean
  stackedFit: Availability
  onStackedChange: (value: boolean) => void
  aggregate: Aggregate
  /** Whether repeated X values are combined, so the choice has an effect. */
  aggregates: boolean
  onAggregateChange: (value: Aggregate) => void
  showGrid: boolean
  showLegend: boolean
  onShowGridChange: (value: boolean) => void
  onShowLegendChange: (value: boolean) => void
}

const NONE = "__none__"

export function ChartConfigPanel({
  columns,
  chartType,
  xOptions,
  yOptions,
  colorOptions = [],
  xAxis,
  yAxes,
  colorBy,
  onXAxisChange,
  onYAxesChange,
  onColorByChange,
  stacked,
  stackedFit,
  onStackedChange,
  aggregate,
  aggregates,
  onAggregateChange,
  showGrid,
  showLegend,
  onShowGridChange,
  onShowLegendChange,
}: ChartConfigPanelProps) {
  const measures = yOptions ?? columns
  const multi = chartType === "line" || chartType === "area" || chartType === "bar"
  const hasX = chartType !== "kpi" && chartType !== "histogram"
  const hasY = chartType !== "kpi"
  const colorLabel = chartType === "heatmap" ? "Rows (second category)"
    : chartType === "scatter" ? "Colour by" : "Series by"
  const hasColor = multi || chartType === "scatter" || chartType === "heatmap"
  const showAggregate = aggregates && (multi || chartType === "heatmap")
  const stackable = chartType === "bar" || chartType === "area"
  const grid = chartType === "line" || chartType === "area" || chartType === "bar"
    || chartType === "scatter" || chartType === "histogram"

  const toggleY = (col: string, on: boolean) => {
    const next = on ? [...yAxes, col] : yAxes.filter(c => c !== col)
    if (next.length > 0) onYAxesChange(next)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Chart Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {chartType === "kpi" && (
          <p className="text-xs text-muted-foreground">
            One tile per numeric column. Nothing to configure.
          </p>
        )}

        {hasX && (
          <div className="space-y-2">
            <Label htmlFor="x-axis">X-Axis</Label>
            <Select value={xAxis} onValueChange={(v) => { if (v !== null) onXAxisChange(v) }}>
              <SelectTrigger id="x-axis">
                <SelectValue placeholder="Select X-axis column" />
              </SelectTrigger>
              <SelectContent>
                {(xOptions ?? columns).map((col) => (
                  <SelectItem key={col} value={col}>{col}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {hasY && (multi ? (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium leading-none">
              Y-Axis <span className="font-normal text-muted-foreground">(up to {MAX_SERIES})</span>
            </legend>
            {colorBy && (
              <p className="text-xs text-muted-foreground">
                One measure per chart while splitting by {colorBy}.
              </p>
            )}
            {measures.map((col) => {
              const on = yAxes.includes(col)
              const blocked = !on && (yAxes.length >= MAX_SERIES || (!!colorBy && yAxes.length >= 1))
              return (
                <div key={col} className="flex items-center space-x-2">
                  <Checkbox
                    id={`y-${col}`}
                    checked={on}
                    disabled={blocked || (on && yAxes.length === 1)}
                    onCheckedChange={(v) => toggleY(col, v === true)}
                  />
                  <Label htmlFor={`y-${col}`} className="text-sm font-normal cursor-pointer truncate">
                    {col}
                  </Label>
                </div>
              )
            })}
          </fieldset>
        ) : (
          <div className="space-y-2">
            <Label htmlFor="y-axis">{chartType === "histogram" ? "Column" : "Y-Axis"}</Label>
            <Select value={yAxes[0] ?? ""} onValueChange={(v) => { if (v !== null) onYAxesChange([v]) }}>
              <SelectTrigger id="y-axis">
                <SelectValue placeholder="Select numeric column" />
              </SelectTrigger>
              <SelectContent>
                {measures.map((col) => (
                  <SelectItem key={col} value={col}>{col}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))}

        {hasColor && (
          <div className="space-y-2">
            <Label htmlFor="color-by">{colorLabel}</Label>
            <Select
              value={colorBy || NONE}
              onValueChange={(v) => { if (v !== null) onColorByChange(v === NONE ? "" : v) }}
            >
              <SelectTrigger id="color-by">
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>None</SelectItem>
                {colorOptions.map((col) => (
                  <SelectItem key={col} value={col}>{col}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {showAggregate && (
          <div className="space-y-2">
            <Label htmlFor="aggregate">Aggregation</Label>
            <Select value={aggregate} onValueChange={(v) => { if (v !== null) onAggregateChange(v as Aggregate) }}>
              <SelectTrigger id="aggregate">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AGGREGATES.map((a) => (
                  <SelectItem key={a} value={a}>{AGGREGATE_LABEL[a]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">Applied where X (or a heatmap cell) repeats.</p>
          </div>
        )}

        {/* Display Options */}
        <div className="space-y-3 pt-2 border-t">
          {stackable && (
            <div className="flex items-center space-x-2" title={stackedFit.ok ? undefined : stackedFit.reason}>
              <Checkbox
                id="stacked"
                checked={stacked}
                disabled={!stackedFit.ok}
                onCheckedChange={(v) => onStackedChange(v === true)}
              />
              <Label htmlFor="stacked" className="text-sm font-normal cursor-pointer">
                Stacked (parts of a whole)
              </Label>
            </div>
          )}
          {stackable && !stackedFit.ok && (
            <p className="text-xs text-muted-foreground">{stackedFit.reason}</p>
          )}
          {grid && (
            <div className="flex items-center space-x-2">
              <Checkbox id="show-grid" checked={showGrid} onCheckedChange={onShowGridChange} />
              <Label htmlFor="show-grid" className="text-sm font-normal cursor-pointer">
                Show Grid
              </Label>
            </div>
          )}
          <div className="flex items-center space-x-2">
            <Checkbox id="show-legend" checked={showLegend} onCheckedChange={onShowLegendChange} />
            <Label htmlFor="show-legend" className="text-sm font-normal cursor-pointer">
              Show Legend
            </Label>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
