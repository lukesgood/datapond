"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { RunDetails } from "@/components/mlflow/run-details"
import { ArrowLeft } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"

interface Experiment {
  name: string
}

interface MlflowRun {
  info: {
    run_id: string
    run_name?: string
    experiment_id: string
    status: string
    start_time: number
    end_time?: number
    lifecycle_stage: string
    user_id?: string
  }
  data: {
    metrics?: Array<{ key: string; value: number; timestamp: number; step: number }>
    params?: Array<{ key: string; value: string }>
    tags?: Array<{ key: string; value: string }>
  }
}

export default function RunDetailPage({
  params,
}: {
  params: { id: string; runId: string }
}) {
  const router = useRouter()
  const [run, setRun] = useState<MlflowRun | null>(null)
  const [experiment, setExperiment] = useState<Experiment | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchRunDetails = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const runRes = await fetch(`/api/mlflow/runs/${params.runId}`)
      if (!runRes.ok) throw new Error(await runRes.text() || `HTTP ${runRes.status}`)
      setRun(await runRes.json() as MlflowRun)

      const expRes = await fetch(`/api/mlflow/experiments/${params.id}`)
      if (!expRes.ok) throw new Error(await expRes.text() || `HTTP ${expRes.status}`)
      setExperiment(await expRes.json() as Experiment)
    } catch (caught) {
      setRun(null)
      setError(caught instanceof Error ? caught.message : "Failed to load run")
    } finally {
      setLoading(false)
    }
  }, [params.id, params.runId])

  useEffect(() => {
    const timer = window.setTimeout(() => { void fetchRunDetails() }, 0)
    return () => window.clearTimeout(timer)
  }, [fetchRunDetails])

  if (loading) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">Loading run...</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (!run) {
    return (
      <div className="flex-1 space-y-4 p-8 pt-6">
        <Card>
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">{error || "Run not found"}</p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="/dashboard">Home</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="/experiments">ML Experiments</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href={`/experiments/${params.id}`}>
              {experiment?.name || "Experiment"}
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>
              Run {run.info.run_name || run.info.run_id.substring(0, 8)}
            </BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Back Button */}
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => router.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Experiment
        </Button>
      </div>

      {/* Run Details Component */}
      <RunDetails run={run} />
    </div>
  )
}
