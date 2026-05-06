import { NextResponse } from "next/server"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000"

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/mlflow/experiments`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error fetching experiments:", error)
    return NextResponse.json({ error: "Failed to fetch experiments" }, { status: 500 })
  }
}
