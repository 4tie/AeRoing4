import type { NextConfig } from 'next';
import dotenv from 'dotenv';

// Load .env into process.env (dotenv.populate is used internally to inject)
dotenv.config({ path: '.env', override: true });

const nextConfig: NextConfig = {
  reactStrictMode: false,
  turbopack: {},
  typescript: {
    ignoreBuildErrors: true,
  },
  env: {
    PROJECT_ID: process.env.HAPPYSEEDS_PROJECT_ID ?? '',
    REACTUS_BASE_URL: process.env.REACTUS_BASE_URL ?? '',
  },
  serverExternalPackages: [],
  allowedDevOrigins: [
    "**.*.*",
  ],
  // Proxy /api/* and /health to the FastAPI backend so the browser
  // never needs to reach port 8000 directly (works behind Replit's proxy).
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';
    return [
      { source: '/api/:path*', destination: `${backendUrl}/api/:path*` },
      { source: '/health',     destination: `${backendUrl}/health` },
      { source: '/docs',       destination: `${backendUrl}/docs` },
      { source: '/redoc',      destination: `${backendUrl}/redoc` },
    ];
  },
};

export default nextConfig;

