"use client"

import { useState, useEffect } from "react"
import { Search, Star, Database, X } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { queryApi, QueryHistoryItem as QueryHistoryItemType } from "@/lib/api"
import { getFavoriteQueries } from "@/lib/favorites"
import { QueryHistoryItem } from "./query-history-item"
import { Skeleton } from "@/components/ui/skeleton"

interface Props {
  onQuerySelect: (queryText: string) => void
  isOpen: boolean
  onToggle: () => void
}

type FilterType = "all" | "favorites"

export function QueryHistorySidebar({ onQuerySelect, isOpen, onToggle }: Props) {
  const [queries, setQueries] = useState<QueryHistoryItemType[]>([])
  const [searchTerm, setSearchTerm] = useState("")
  const [filter, setFilter] = useState<FilterType>("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadHistory()
  }, [])

  const loadHistory = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await queryApi.history(50, 0)
      setQueries(data.items)
    } catch (error) {
      console.error("Failed to load history:", error)
      setError(error instanceof Error ? error.message : "Failed to load history")
    } finally {
      setLoading(false)
    }
  }

  const handleQuerySelect = (queryText: string) => {
    onQuerySelect(queryText)
  }

  // Filter queries based on search and favorites
  const filteredQueries = queries.filter(q => {
    const matchesSearch = q.query_text.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesFilter = filter === "all" || (filter === "favorites" && getFavoriteQueries().includes(q.id))
    return matchesSearch && matchesFilter
  })

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="px-3 py-2 border-b space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">History</span>
          <Button variant="ghost" size="sm" onClick={onToggle} className="h-6 w-6 p-0">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-7 pr-7 h-8 text-xs"
          />
          {searchTerm && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSearchTerm("")}
              className="absolute right-1 top-1 h-7 w-7 p-0"
            >
              <X className="h-3 w-3" />
            </Button>
          )}
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1">
          <Button
            variant={filter === "all" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setFilter("all")}
            className="flex-1 h-7 text-xs"
          >
            All {queries.length > 0 && `(${queries.length})`}
          </Button>
          <Button
            variant={filter === "favorites" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setFilter("favorites")}
            className="flex-1 h-7 text-xs gap-1"
          >
            <Star className="h-3 w-3" />
            Starred
          </Button>
        </div>
      </div>

      {/* Query list */}
      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="p-3 space-y-2">
                <Skeleton className="h-10 w-full" />
                <div className="flex gap-2">
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-20 ml-auto" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="text-center text-red-500 mt-8 px-4">
            <Database className="h-12 w-12 mx-auto mb-2 text-red-300" />
            <p className="text-sm font-medium">Failed to load history</p>
            <p className="text-xs mt-1">{error}</p>
            <Button
              size="sm"
              variant="outline"
              onClick={loadHistory}
              className="mt-3"
            >
              Retry
            </Button>
          </div>
        ) : filteredQueries.length === 0 ? (
          <div className="text-center text-gray-500 mt-8 px-4">
            <Database className="h-12 w-12 mx-auto mb-2 text-gray-300" />
            {queries.length === 0 ? (
              <p className="text-sm">No query history yet. Run a query to get started!</p>
            ) : filter === "favorites" ? (
              <p className="text-sm">No favorite queries yet. Star queries to save them here!</p>
            ) : (
              <p className="text-sm">No queries match your search.</p>
            )}
          </div>
        ) : (
          <div className="space-y-1">
            {filteredQueries.map(query => (
              <QueryHistoryItem
                key={query.id}
                query={query}
                onSelect={handleQuerySelect}
              />
            ))}
          </div>
        )}
      </div>

      {/* Refresh button at bottom */}
      {!loading && (
        <div className="p-2 border-t">
          <Button
            variant="ghost"
            size="sm"
            onClick={loadHistory}
            className="w-full h-7 text-xs text-muted-foreground"
          >
            Refresh
          </Button>
        </div>
      )}
    </div>
  )
}
