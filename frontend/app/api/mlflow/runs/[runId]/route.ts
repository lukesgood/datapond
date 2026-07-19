import { NextRequest } from "next/server"
import { proxyMlflow } from "../../_proxy"

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params
  return proxyMlflow(request, `/runs/${encodeURIComponent(runId)}`)
}
