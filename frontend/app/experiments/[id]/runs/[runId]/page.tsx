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
import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"

export default function RunDetailPage({
  params,
}: {
  params: { id: string; runId: string }
}) {
  const router = useRouter()
  const [run, setRun] = useState<any>(null)
  const [experiment, setExperiment] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchRunDetails()
  }, [params.runId])

  const fetchRunDetails = async () => {
    setLoading(true)
    try {
      // Fetch run info
      const runRes = await fetch(`/api/mlflow/runs/${params.runId}`)
      const runData = await runRes.json()
      setRun(runData.run)

      // Fetch experiment info for breadcrumb
      const expRes = await fetch(`/api/mlflow/experiments/${params.id}`)
      const expData = await expRes.json()
      setExperiment(expData.experiment)
    } catch (error) {
      console.error("Error fetching run details:", error)
    } finally {
      setLoading(false)
    }
  }

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
            <p className="text-muted-foreground">Run not found</p>
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
