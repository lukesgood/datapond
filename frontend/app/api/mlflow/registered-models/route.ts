import { NextRequest } from "next/server"
import { proxyMlflow } from "../_proxy"

export async function GET(request: NextRequest) {
  return proxyMlflow(request, "/models")
}
