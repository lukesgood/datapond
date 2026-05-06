import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const response = await fetch(`${BACKEND_URL}/api/mlflow/experiments/${id}/runs`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error fetching runs:", error)
    return NextResponse.json({ error: "Failed to fetch runs" }, { status: 500 })
  }
}
