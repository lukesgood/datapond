import { NextResponse } from "next/server"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000"

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/mlflow/registered-models`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Error fetching registered models:", error)
    return NextResponse.json({ error: "Failed to fetch models" }, { status: 500 })
  }
}
