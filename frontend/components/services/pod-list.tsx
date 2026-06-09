"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  CheckCircle2,
  AlertCircle,
  Clock,
  FileText,
  Trash2,
  RefreshCw,
} from "lucide-react"
import { formatDistanceToNow } from "date-fns"

interface Pod {
  name: string
  status: "Running" | "Pending" | "Failed" | "Succeeded" | "Unknown"
  restarts: number
  age: string
  cpu_usage?: number
  memory_usage?: number
}

interface PodListProps {
  pods: Pod[]
  onViewLogs?: (podName: string) => void
  onDeletePod?: (podName: string) => void
  onRefresh?: () => void
}

export function PodList({
  pods,
  onViewLogs,
  onDeletePod,
  onRefresh,
}: PodListProps) {
  const [selectedPod, setSelectedPod] = useState<Pod | null>(null)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "Running":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />
      case "Failed":
        return <AlertCircle className="h-4 w-4 text-red-500" />
      case "Pending":
        return <Clock className="h-4 w-4 text-yellow-500" />
      default:
        return <Clock className="h-4 w-4 text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "Running":
        return (
          <Badge variant="default" className="bg-green-600">
            Running
          </Badge>
        )
      case "Failed":
        return <Badge variant="destructive">Failed</Badge>
      case "Pending":
        return (
          <Badge variant="secondary" className="bg-yellow-600">
            Pending
          </Badge>
        )
      case "Succeeded":
        return (
          <Badge variant="default" className="bg-blue-600">
            Succeeded
          </Badge>
        )
      default:
        return <Badge variant="secondary">Unknown</Badge>
    }
  }

  const handleDeleteClick = (pod: Pod) => {
    setSelectedPod(pod)
    setShowDeleteDialog(true)
  }

  const handleDeleteConfirm = () => {
    if (selectedPod && onDeletePod) {
      onDeletePod(selectedPod.name)
    }
    setShowDeleteDialog(false)
    setSelectedPod(null)
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              Pods
              <Badge variant="secondary">{pods.length}</Badge>
            </CardTitle>
            {onRefresh && (
              <Button variant="outline" size="sm" onClick={onRefresh}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {pods.length > 0 ? (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="text-center">Restarts</TableHead>
                    <TableHead>CPU</TableHead>
                    <TableHead>Memory</TableHead>
                    <TableHead>Age</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pods.map((pod) => (
                    <TableRow key={pod.name}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {getStatusIcon(pod.status)}
                          {getStatusBadge(pod.status)}
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {pod.name}
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant={pod.restarts > 3 ? "destructive" : "secondary"}
                        >
                          {pod.restarts}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {pod.cpu_usage ? `${pod.cpu_usage.toFixed(1)}%` : "N/A"}
                      </TableCell>
                      <TableCell>
                        {pod.memory_usage
                          ? `${pod.memory_usage.toFixed(1)}%`
                          : "N/A"}
                      </TableCell>
                      <TableCell>{pod.age}</TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-2">
                          {onViewLogs && (
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => onViewLogs(pod.name)}
                              aria-label="View logs" title="View logs"
                            >
                              <FileText className="h-3 w-3" />
                            </Button>
                          )}
                          {onDeletePod && (
                            <Button
                              variant="ghost"
                              size="icon-xs"
                              onClick={() => handleDeleteClick(pod)}
                              aria-label="Delete pod (restart)" title="Delete pod (restart)"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="text-muted-foreground text-center py-8">
              No pods available
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Pod</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete this pod? This will trigger
              Kubernetes to restart the pod.
            </DialogDescription>
          </DialogHeader>
          {selectedPod && (
            <div className="py-4">
              <div className="font-mono text-sm bg-muted p-3 rounded">
                {selectedPod.name}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
            >
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteConfirm}>
              Delete Pod
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
