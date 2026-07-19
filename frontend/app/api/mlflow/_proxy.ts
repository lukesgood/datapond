import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL || "http://backend:8000").replace(/\/$/, "")

interface ProxyOptions {
  method?: string
  body?: BodyInit | null
  contentType?: string | null
  includeSearch?: boolean
}

export async function proxyMlflow(
  request: NextRequest,
  backendPath: string,
  options: ProxyOptions = {},
): Promise<Response> {
  const method = options.method ?? request.method
  const headers = new Headers()
  const authorization = request.headers.get("authorization")
  if (authorization) headers.set("authorization", authorization)

  const contentType = options.contentType === undefined
    ? request.headers.get("content-type")
    : options.contentType
  if (contentType) headers.set("content-type", contentType)
  const accept = request.headers.get("accept")
  if (accept) headers.set("accept", accept)

  let body = options.body
  if (body === undefined && method !== "GET" && method !== "HEAD") {
    body = await request.arrayBuffer()
  }
  const search = options.includeSearch === false ? "" : request.nextUrl.search

  try {
    const upstream = await fetch(`${BACKEND_URL}/api/mlflow${backendPath}${search}`, {
      method,
      headers,
      body,
      cache: "no-store",
    })
    const responseHeaders = new Headers()
    for (const name of ["content-type", "content-disposition", "www-authenticate"]) {
      const value = upstream.headers.get(name)
      if (value) responseHeaders.set(name, value)
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    })
  } catch (error) {
    console.error("MLflow backend proxy failed:", error)
    return NextResponse.json(
      { detail: "MLflow backend is unavailable" },
      { status: 502 },
    )
  }
}
