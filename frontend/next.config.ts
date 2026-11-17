import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone", // self-contained server for the Docker image
  // The browser only talks to this Next.js app; /api/* is proxied to the FastAPI backend.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  images: { unoptimized: true },
};

export default nextConfig;
