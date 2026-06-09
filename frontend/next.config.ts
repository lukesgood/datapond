import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/:path*`
          : process.env.NODE_ENV === "production"
          ? "http://backend.datapond.svc.cluster.local:8000/api/:path*"
          : "http://localhost:8000/api/:path*",
      },
    ];
  },
  // Force HTML/RSC pages to revalidate so deploys propagate immediately. Without this,
  // prerendered pages ship Cache-Control: s-maxage=1yr, which (behind any shared cache
  // or in the browser/bfcache) keeps serving stale JS-chunk references after a deploy —
  // the SPA then runs an old build until a manual hard refresh. Content-hashed assets
  // under /_next/static stay immutable (safe to cache forever).
  async headers() {
    return [
      {
        source: "/_next/static/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
      {
        // Everything else (HTML pages + RSC payloads). Exclude immutable static assets.
        source: "/((?!_next/static/|_next/image).*)",
        headers: [{ key: "Cache-Control", value: "no-cache, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
