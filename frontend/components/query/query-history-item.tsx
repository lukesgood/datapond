"use client"

import { useState } from "react"
import { Star, Clock, CheckCircle, XCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDistanceToNow } from "date-fns"
import { QueryHistoryItem as QueryHistoryItemType } from "@/lib/api"
import { isFavorite, toggleFavorite } from "@/lib/favorites"

interface Props {
  query: QueryHistoryItemType
  onSelect: (queryText: string) => void
}

export function QueryHistoryItem({ query, onSelect }: Props) {
  const [isFav, setIsFav] = useState(isFavorite(query.id))

  const handleFavoriteClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    const newFavState = toggleFavorite(query.id)
    setIsFav(newFavState)
  }

  const truncateQuery = (text: string, maxLength: number = 100) => {
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + "..."
  }

  const formatTime = (ms: number) => {
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(2)}s`
  }

  return (
    <div
      onClick={() => onSelect(query.query_text)}
      className="group relative p-3 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors border border-transparent hover:border-gray-200"
    >
      {/* Star favorite button */}
      <Button
        variant="ghost"
        size="sm"
        className="absolute top-2 right-2 h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={handleFavoriteClick}
      >
        <Star
          className={`h-3.5 w-3.5 ${
            isFav ? "fill-yellow-400 text-yellow-400" : "text-gray-400"
          }`}
        />
      </Button>

      {/* Query text */}
      <div className="mb-2 pr-8">
        <code className="text-xs font-mono text-gray-700 line-clamp-2">
          {truncateQuery(query.query_text)}
        </code>
      </div>

      {/* Metadata */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Status */}
        {query.status === "success" ? (
          <div className="flex items-center gap-1 text-green-600">
            <CheckCircle className="h-3 w-3" />
            <span className="text-xs">Success</span>
          </div>
        ) : (
          <div className="flex items-center gap-1 text-red-600">
            <XCircle className="h-3 w-3" />
            <span className="text-xs">Error</span>
          </div>
        )}

        {/* Execution time */}
        <Badge variant="secondary" className="text-xs">
          {formatTime(query.execution_time_ms)}
        </Badge>

        {/* Rows returned (only for successful queries) */}
        {query.status === "success" && (
          <Badge variant="outline" className="text-xs">
            {query.rows_returned} rows
          </Badge>
        )}

        {/* Timestamp */}
        <div className="flex items-center gap-1 text-xs text-gray-500 ml-auto">
          <Clock className="h-3 w-3" />
          <span>
            {formatDistanceToNow(new Date(query.created_at), { addSuffix: true })}
          </span>
        </div>
      </div>

      {/* Error message (if any) */}
      {query.error_message && (
        <div className="mt-2 text-xs text-red-600 line-clamp-1">
          {query.error_message}
        </div>
      )}
    </div>
  )
}
