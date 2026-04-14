/** @type {import('next').NextConfig} */
const FASTAPI = process.env.FASTAPI_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Proxy API calls, legacy UI, and legacy static assets to the FastAPI backend.
  // This keeps the same origin in the browser, so cookies/auth work without CORS.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${FASTAPI}/api/:path*` },
      { source: "/legacy", destination: `${FASTAPI}/legacy` },
      { source: "/legacy/:path*", destination: `${FASTAPI}/legacy/:path*` },
      { source: "/static/:path*", destination: `${FASTAPI}/static/:path*` },
    ];
  },
};

export default nextConfig;
