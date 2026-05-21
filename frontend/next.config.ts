import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/:path*`
          : process.env.NODE_ENV === "production"
          ? "http://backend.datapond.svc.cluster.local:8000/:path*"
          : "http://localhost:8000/:path*",
      },
    ];
  },
};

export default nextConfig;
