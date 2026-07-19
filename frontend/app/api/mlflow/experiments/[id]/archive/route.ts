import { NextRequest } from "next/server"
import { proxyMlflow } from "../../../_proxy"

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  return proxyMlflow(request, `/experiments/${encodeURIComponent(id)}/archive`)
}
