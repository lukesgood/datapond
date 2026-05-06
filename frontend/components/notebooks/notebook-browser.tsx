"use client"

import { useState } from "react"
import { ChevronRight, ChevronDown, Folder, FileCode, Upload } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

interface FileNode {
  name: string
  path: string
  type: "folder" | "notebook" | "file"
  children?: FileNode[]
}

interface NotebookBrowserProps {
  files: FileNode[]
  currentPath: string
  onNavigate: (path: string) => void
  onFileClick: (file: FileNode) => void
  onUpload?: () => void
}

export function NotebookBrowser({
  files,
  currentPath,
  onNavigate,
  onFileClick,
  onUpload,
}: NotebookBrowserProps) {
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set(["/notebooks"]))

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(path)) {
      newExpanded.delete(path)
    } else {
      newExpanded.add(path)
    }
    setExpandedFolders(newExpanded)
  }

  const pathParts = currentPath.split("/").filter(Boolean)

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    return nodes.map((node) => {
      const isExpanded = expandedFolders.has(node.path)
      const isFolder = node.type === "folder"

      return (
        <div key={node.path} style={{ paddingLeft: `${depth * 12}px` }}>
          <div
            className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer hover:bg-accent transition-colors ${
              currentPath === node.path ? "bg-accent" : ""
            }`}
            onClick={() => {
              if (isFolder) {
                toggleFolder(node.path)
                onNavigate(node.path)
              } else {
                onFileClick(node)
              }
            }}
          >
            {isFolder && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  toggleFolder(node.path)
                }}
                className="p-0.5 hover:bg-muted rounded"
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </button>
            )}
            {!isFolder && <div className="w-5" />}

            {isFolder ? (
              <Folder className="h-4 w-4 text-blue-500" />
            ) : (
              <FileCode className="h-4 w-4 text-purple-500" />
            )}

            <span className="text-sm flex-1 truncate">{node.name}</span>
          </div>

          {isFolder && isExpanded && node.children && (
            <div className="mt-1">
              {renderFileTree(node.children, depth + 1)}
            </div>
          )}
        </div>
      )
    })
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Notebooks</CardTitle>
          {onUpload && (
            <Button variant="outline" size="sm" onClick={onUpload}>
              <Upload className="mr-2 h-4 w-4" />
              Upload
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-2">
        <div className="mb-3 px-2">
          <Breadcrumb>
            <BreadcrumbList>
              <BreadcrumbItem>
                <BreadcrumbLink
                  href="#"
                  onClick={(e) => {
                    e.preventDefault()
                    onNavigate("/notebooks")
                  }}
                >
                  notebooks
                </BreadcrumbLink>
              </BreadcrumbItem>
              {pathParts.slice(1).map((part, idx) => (
                <span key={idx} className="contents">
                  <BreadcrumbSeparator />
                  <BreadcrumbItem>
                    {idx === pathParts.length - 2 ? (
                      <BreadcrumbPage>{part}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink
                        href="#"
                        onClick={(e) => {
                          e.preventDefault()
                          const path = "/" + pathParts.slice(0, idx + 2).join("/")
                          onNavigate(path)
                        }}
                      >
                        {part}
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </span>
              ))}
            </BreadcrumbList>
          </Breadcrumb>
        </div>

        <div className="space-y-1 max-h-[400px] overflow-y-auto">
          {renderFileTree(files)}
        </div>
      </CardContent>
    </Card>
  )
}
