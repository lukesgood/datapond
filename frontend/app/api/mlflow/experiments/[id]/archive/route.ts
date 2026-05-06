import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000"

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const response = await fetch(
      `${BACKEND_URL}/api/mlflow/experiments/${id}/archive`,
      { method: "POST" }
    )
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error archiving experiment:", error)
    return NextResponse.json({ error: "Failed to archive experiment" }, { status: 500 })
  }
}
