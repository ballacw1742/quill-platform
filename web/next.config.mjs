/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typescript: {
    // TypeScript errors are caught in CI; skip during Docker builds
    ignoreBuildErrors: true,
  },
  eslint: {
    // ESLint is run separately in CI; skip during Docker builds
    ignoreDuringBuilds: true,
  },
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [{ protocol: "https", hostname: "**" }],
  },
  async rewrites() {
    const apiBase = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL;
    if (!apiBase || process.env.NEXT_PUBLIC_USE_MOCK === "1") return [];
    return [
      { source: "/api/v1/:path*", destination: `${apiBase}/v1/:path*` },
      { source: "/ws/:path*", destination: `${apiBase}/ws/:path*` },
    ];
  },
};
export default nextConfig;
