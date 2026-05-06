import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> }
) {
  try {
    const { runId } = await params
    const response = await fetch(`${BACKEND_URL}/api/mlflow/runs/${runId}`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error fetching run:", error)
    return NextResponse.json({ error: "Failed to fetch run" }, { status: 500 })
  }
}
