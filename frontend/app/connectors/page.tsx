"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ConnectorCard } from "@/components/connectors/connector-card"
import { availableConnectors } from "@/lib/connectors"
import {
  Plus, RefreshCw, Database, Search, MoreHorizontal,
  Trash2, HardDrive, Radio, Cloud, AlertCircle, Plug,
} from "lucide-react"
import Link from "next/link"

interface Connection {
  id: string
  name: string
  connector_type: string
  status: "active" | "paused" | "error" | "pending"
  created_at: string
  last_sync_at: string | null
}

export default function ConnectorsPage() {
  // ── Connections state ──────────────────────────────────────────────────────
  const [connections, setConnections] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchConnections = async () => {
    try {
      setError(null)
      const res = await fetch("/api/connectors/connections")
      if (!res.ok) throw new Error(`Failed to load (${res.status})`)
      const data = await res.json()
      setConnections(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load connections")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchConnections() }, [])

  const handleSync = async (id: string) => {
    setActionLoading(id)
    try {
      await fetch(`/api/connectors/${id}/sync`, { method: "POST" })
      await fetchConnections()
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this connection?")) return
    setActionLoading(id)
    try {
      await fetch(`/api/connectors/${id}`, { method: "DELETE" })
      setConnections(prev => prev.filter(c => c.id !== id))
    } finally {
      setActionLoading(null)
    }
  }

  // ── Marketplace state ──────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState("")
  const [marketCat, setMarketCat] = useState("all")

  const filteredConnectors = availableConnectors.filter(c =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.description.toLowerCase().includes(searchQuery.toLowerCase())
  ).filter(c => marketCat === "all" || c.category === marketCat)

  // ── Helpers ────────────────────────────────────────────────────────────────
  const formatDate = (s: string | null) => {
    if (!s) return "Never"
    return new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    }).format(new Date(s))
  }

  const statusBadge = (status: string) => {
    if (status === "active")
      return <Badge className="bg-emerald-500/15 text-emerald-700 border-emerald-200 text-[10px] h-5">Active</Badge>
    if (status === "error")
      return <Badge variant="destructive" className="text-[10px] h-5">Error</Badge>
    return <Badge variant="secondary" className="text-[10px] h-5 capitalize">{status}</Badge>
  }

  const activeCount = connections.filter(c => c.status === "active").length
  const errorCount  = connections.filter(c => c.status === "error").length

  return (
    <div className="flex-1 space-y-5 px-6 py-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Connectors</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            데이터 소스 연결 관리
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5"
            onClick={fetchConnections} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Tabs: Connections (default) + Marketplace */}
      <Tabs defaultValue="connections" className="space-y-4">
        <div className="flex items-center justify-between">
          <TabsList className="h-8">
            <TabsTrigger value="connections" className="text-xs h-7 gap-1.5">
              <Plug className="h-3.5 w-3.5" />
              Active Connections
              {connections.length > 0 && (
                <Badge variant="secondary" className="text-[9px] h-4 px-1 ml-0.5">
                  {connections.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="marketplace" className="text-xs h-7 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              Add Connection
            </TabsTrigger>
          </TabsList>
        </div>

        {/* ── Active Connections tab ─────────────────────────────────────── */}
        <TabsContent value="connections" className="space-y-4">

          {/* Stats */}
          <div className="flex items-center gap-4 text-sm">
            <span className="text-muted-foreground">
              <span className="font-semibold text-foreground">{connections.length}</span> total
            </span>
            <span className="text-emerald-600">
              <span className="font-semibold">{activeCount}</span> active
            </span>
            {errorCount > 0 && (
              <span className="text-red-500 flex items-center gap-1">
                <AlertCircle className="h-3.5 w-3.5" />
                <span className="font-semibold">{errorCount}</span> error
              </span>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30
                            bg-destructive/5 px-4 py-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {/* Table */}
          <div className="rounded-lg border overflow-hidden">
            <Table>
              <TableHeader className="bg-muted/40">
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Type</TableHead>
                  <TableHead className="text-xs">Status</TableHead>
                  <TableHead className="text-xs">Last Sync</TableHead>
                  <TableHead className="text-xs">Created</TableHead>
                  <TableHead className="text-xs w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  Array(3).fill(0).map((_, i) => (
                    <TableRow key={i}>
                      {Array(6).fill(0).map((_, j) => (
                        <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : connections.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-16 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <Database className="h-10 w-10 text-muted-foreground/30" />
                        <p className="text-sm text-muted-foreground">No connections yet</p>
                        <p className="text-xs text-muted-foreground/60">
                          Click <strong>Add Connection</strong> tab to connect a data source
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  connections.map(conn => (
                    <TableRow
                      key={conn.id}
                      className={actionLoading === conn.id ? "opacity-50" : ""}
                    >
                      <TableCell className="font-medium text-sm">
                        <Link href={`/connectors/connections/${conn.id}`}
                          className="hover:underline underline-offset-2">
                          {conn.name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <span className="flex items-center gap-1.5 text-sm">
                          <Database className="h-3.5 w-3.5 text-muted-foreground" />
                          <span className="capitalize">{conn.connector_type}</span>
                        </span>
                      </TableCell>
                      <TableCell>{statusBadge(conn.status)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(conn.last_sync_at)}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(conn.created_at)}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger>
                            <Button variant="ghost" size="icon"
                              className="h-7 w-7" disabled={actionLoading === conn.id}>
                              <MoreHorizontal className="h-3.5 w-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => handleSync(conn.id)}>
                              <RefreshCw className="h-3.5 w-3.5 mr-2" />Sync Now
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={() => handleDelete(conn.id)}>
                              <Trash2 className="h-3.5 w-3.5 mr-2" />Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {/* ── Marketplace tab ────────────────────────────────────────────── */}
        <TabsContent value="marketplace" className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Search connectors..."
                className="pl-8 h-8 text-sm"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="flex gap-1">
              {[
                { id: "all", label: "All", icon: Cloud },
                { id: "database", label: "Databases", icon: Database },
                { id: "storage", label: "Storage", icon: HardDrive },
                { id: "streaming", label: "Streaming", icon: Radio },
              ].map(({ id, label, icon: Icon }) => (
                <Button
                  key={id}
                  variant={marketCat === id ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 text-xs gap-1.5"
                  onClick={() => setMarketCat(id)}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </Button>
              ))}
            </div>
          </div>

          {filteredConnectors.length === 0 ? (
            <div className="py-16 text-center text-sm text-muted-foreground">
              No connectors found
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredConnectors.map(connector => (
                <ConnectorCard key={connector.id} connector={connector} />
              ))}
            </div>
          )}

          <div className="border-t pt-3 flex justify-between text-xs text-muted-foreground">
            <span>{availableConnectors.filter(c => c.supported).length} available</span>
            <span>{availableConnectors.filter(c => !c.supported).length} coming soon</span>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
