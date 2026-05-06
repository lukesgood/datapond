"use client"

import { useState } from "react"
import { formatDistanceToNow } from "date-fns"
import {
  FileCode,
  MoreVertical,
  ExternalLink,
  Edit,
  Copy,
  Trash,
  Download,
  Clock,
  HardDrive,
} from "lucide-react"
import { Card, CardContent, CardFooter } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Badge } from "@/components/ui/badge"

interface NotebookCardProps {
  notebook: {
    name: string
    path: string
    last_modified: string
    size?: string
    type: string
    kernel?: string
  }
  onOpen: (notebook: any) => void
  onRename?: (notebook: any) => void
  onDelete?: (notebook: any) => void
  onDuplicate?: (notebook: any) => void
}

export function NotebookCard({
  notebook,
  onOpen,
  onRename,
  onDelete,
  onDuplicate,
}: NotebookCardProps) {
  const [isHovered, setIsHovered] = useState(false)

  const handleDownload = () => {
    // In production, this would download the notebook file
    const link = document.createElement("a")
    link.href = `/api/notebooks/download?path=${encodeURIComponent(notebook.path)}`
    link.download = notebook.name
    link.click()
  }

  return (
    <Card
      className="group relative overflow-hidden cursor-pointer transition-all hover:shadow-md hover:border-primary/50"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={() => onOpen(notebook)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className="mt-0.5">
              <FileCode className="h-5 w-5 text-blue-500" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-sm truncate mb-1">
                {notebook.name}
              </h3>
              <p className="text-xs text-muted-foreground truncate">
                {notebook.path}
              </p>
            </div>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger
              onClick={(e) => e.stopPropagation()}
              className={`inline-flex items-center justify-center rounded-md text-sm font-medium transition-opacity focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 hover:bg-accent hover:text-accent-foreground h-8 w-8 p-0 ${
                isHovered ? "opacity-100" : "opacity-0"
              }`}
            >
              <MoreVertical className="h-4 w-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={(e) => {
                e.stopPropagation()
                onOpen(notebook)
              }}>
                <ExternalLink className="mr-2 h-4 w-4" />
                Open
              </DropdownMenuItem>
              {onRename && (
                <DropdownMenuItem onClick={(e) => {
                  e.stopPropagation()
                  onRename(notebook)
                }}>
                  <Edit className="mr-2 h-4 w-4" />
                  Rename
                </DropdownMenuItem>
              )}
              {onDuplicate && (
                <DropdownMenuItem onClick={(e) => {
                  e.stopPropagation()
                  onDuplicate(notebook)
                }}>
                  <Copy className="mr-2 h-4 w-4" />
                  Duplicate
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={(e) => {
                e.stopPropagation()
                handleDownload()
              }}>
                <Download className="mr-2 h-4 w-4" />
                Download
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {onDelete && (
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(notebook)
                  }}
                  className="text-destructive"
                >
                  <Trash className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {notebook.last_modified}
          </div>
          {notebook.size && (
            <div className="flex items-center gap-1">
              <HardDrive className="h-3 w-3" />
              {notebook.size}
            </div>
          )}
        </div>

        {notebook.kernel && (
          <div className="mt-2">
            <Badge variant="secondary" className="text-xs">
              {notebook.kernel}
            </Badge>
          </div>
        )}
      </CardContent>

      <CardFooter className="p-4 pt-0">
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={(e) => {
            e.stopPropagation()
            onOpen(notebook)
          }}
        >
          <ExternalLink className="mr-2 h-4 w-4" />
          Open Notebook
        </Button>
      </CardFooter>
    </Card>
  )
}
