"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Table as TableIcon, Eye, Database } from "lucide-react"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

interface TableSchema {
  name: string
  schema: string
  row_count?: number
  columns: Array<{
    name: string
    type: string
    nullable: boolean
  }>
}

interface TableSelectorProps {
  tables: TableSchema[]
  selectedTables: string[]
  onToggle: (tableName: string) => void
  onToggleAll: (selected: boolean) => void
}

export function TableSelector({
  tables,
  selectedTables,
  onToggle,
  onToggleAll
}: TableSelectorProps) {
  const [previewTable, setPreviewTable] = useState<TableSchema | null>(null)

  const allSelected = tables.length > 0 && selectedTables.length === tables.length
  const someSelected = selectedTables.length > 0 && selectedTables.length < tables.length

  return (
    <div className="space-y-4">
      {/* Header with select all */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Checkbox
            id="select-all"
            checked={allSelected}
            onCheckedChange={onToggleAll}
            className={someSelected ? "data-[state=checked]:bg-primary/50" : ""}
          />
          <label htmlFor="select-all" className="text-sm font-medium cursor-pointer">
            Select All ({selectedTables.length}/{tables.length})
          </label>
        </div>
        <Badge variant="secondary">
          <Database className="h-3 w-3 mr-1" />
          {tables.length} tables found
        </Badge>
      </div>

      {/* Tables grid */}
      <div className="grid gap-3 md:grid-cols-2">
        {tables.map((table) => {
          const isSelected = selectedTables.includes(table.name)

          return (
            <Card
              key={table.name}
              className={`cursor-pointer transition-colors ${
                isSelected ? "border-primary bg-primary/5" : "hover:border-muted-foreground/50"
              }`}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center space-x-3 flex-1">
                    <Checkbox
                      id={`table-${table.name}`}
                      checked={isSelected}
                      onCheckedChange={() => onToggle(table.name)}
                    />
                    <label
                      htmlFor={`table-${table.name}`}
                      className="flex-1 cursor-pointer"
                    >
                      <div className="flex items-center gap-2">
                        <TableIcon className="h-4 w-4 text-muted-foreground" />
                        <div>
                          <CardTitle className="text-sm font-medium">
                            {table.name}
                          </CardTitle>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {table.schema && `${table.schema}.`}
                            {table.columns.length} columns
                            {table.row_count && ` · ${table.row_count.toLocaleString()} rows`}
                          </p>
                        </div>
                      </div>
                    </label>
                  </div>

                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      setPreviewTable(table)
                    }}
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
            </Card>
          )
        })}
      </div>

      {tables.length === 0 && (
        <div className="text-center py-12 border rounded-lg">
          <Database className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
          <p className="text-muted-foreground">No tables found</p>
        </div>
      )}

      {/* Schema Preview Dialog */}
      <Dialog open={!!previewTable} onOpenChange={() => setPreviewTable(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <TableIcon className="h-5 w-5" />
              {previewTable?.name}
            </DialogTitle>
            <DialogDescription>
              {previewTable?.schema && `Schema: ${previewTable.schema} · `}
              {previewTable?.columns.length} columns
              {previewTable?.row_count && ` · ${previewTable.row_count.toLocaleString()} rows`}
            </DialogDescription>
          </DialogHeader>

          <div className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Column</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Nullable</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {previewTable?.columns.map((column) => (
                  <TableRow key={column.name}>
                    <TableCell className="font-medium">{column.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono text-xs">
                        {column.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {column.nullable ? (
                        <Badge variant="secondary">Yes</Badge>
                      ) : (
                        <Badge variant="outline">No</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
