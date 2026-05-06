"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Clock, Trash2 } from "lucide-react"
import { formatDistanceToNow } from "date-fns"

interface HistoryItem {
  query: string
  timestamp: number
}

interface QueryHistoryProps {
  onQuerySelect: (query: string) => void
}

const MAX_HISTORY_ITEMS = 10
const STORAGE_KEY = "datapond_query_history"

export function QueryHistory({ onQuerySelect }: QueryHistoryProps) {
  const [history, setHistory] = useState<HistoryItem[]>([])

  useEffect(() => {
    loadHistory()
  }, [])

  const loadHistory = () => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        setHistory(JSON.parse(stored))
      }
    } catch (error) {
      console.error("Failed to load query history:", error)
    }
  }

  const clearHistory = () => {
    localStorage.removeItem(STORAGE_KEY)
    setHistory([])
  }

  const truncateQuery = (query: string, maxLength: number = 60) => {
    if (query.length <= maxLength) return query
    return query.substring(0, maxLength) + "..."
  }

  return (
    <Card className="h-full overflow-auto">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Query History</CardTitle>
          {history.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearHistory}
              className="h-8 px-2"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {history.length === 0 ? (
          <p className="text-sm text-muted-foreground">No query history</p>
        ) : (
          history.map((item, index) => (
            <Button
              key={index}
              variant="ghost"
              size="sm"
              className="w-full justify-start font-normal h-auto py-2 px-3"
              onClick={() => onQuerySelect(item.query)}
            >
              <div className="flex flex-col items-start gap-1 w-full">
                <code className="text-xs font-mono bg-muted px-2 py-1 rounded">
                  {truncateQuery(item.query)}
                </code>
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {formatDistanceToNow(item.timestamp, { addSuffix: true })}
                </span>
              </div>
            </Button>
          ))
        )}
      </CardContent>
    </Card>
  )
}

export function addToQueryHistory(query: string) {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    const history: HistoryItem[] = stored ? JSON.parse(stored) : []

    // Add new query at the beginning
    const newHistory = [
      { query, timestamp: Date.now() },
      ...history.filter((item) => item.query !== query), // Remove duplicates
    ].slice(0, MAX_HISTORY_ITEMS)

    localStorage.setItem(STORAGE_KEY, JSON.stringify(newHistory))
  } catch (error) {
    console.error("Failed to save query history:", error)
  }
}
