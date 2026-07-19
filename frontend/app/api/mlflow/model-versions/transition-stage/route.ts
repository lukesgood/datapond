import { NextRequest, NextResponse } from "next/server"
import { proxyMlflow } from "../../_proxy"

interface TransitionBody {
  name?: unknown
  version?: unknown
  stage?: unknown
  archive_existing_versions?: unknown
}

export async function POST(request: NextRequest) {
  let input: TransitionBody
  try {
    input = await request.json() as TransitionBody
  } catch {
    return NextResponse.json({ detail: "Request body must be valid JSON" }, { status: 400 })
  }
  if (typeof input.name !== "string" || typeof input.version !== "string" || typeof input.stage !== "string") {
    return NextResponse.json(
      { detail: "name, version, and stage are required" },
      { status: 400 },
    )
  }
  const body = JSON.stringify({
    stage: input.stage,
    archive_existing_versions: input.archive_existing_versions === true,
  })
  return proxyMlflow(
    request,
    `/models/${encodeURIComponent(input.name)}/versions/${encodeURIComponent(input.version)}/transition`,
    { method: "POST", body, contentType: "application/json", includeSearch: false },
  )
}
