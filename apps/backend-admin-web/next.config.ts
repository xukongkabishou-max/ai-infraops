import type { NextConfig } from "next";
import { networkInterfaces } from "node:os";

const backendApiUrl = process.env.BACKEND_RBAC_API_URL ?? "http://127.0.0.1:8000";

function getLocalDevOrigins() {
  return Object.values(networkInterfaces())
    .flatMap((addresses) => addresses ?? [])
    .filter((address) => address.family === "IPv4" && !address.internal)
    .map((address) => address.address);
}

const nextConfig: NextConfig = {
  allowedDevOrigins: getLocalDevOrigins(),
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
