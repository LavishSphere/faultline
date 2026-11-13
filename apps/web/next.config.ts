import type { NextConfig } from "next";

// The app has no API routes or server actions; all data is fetched client-side from NEXT_PUBLIC_API_BASE.
// FAULTLINE_STATIC_EXPORT=1 produces a static export in `out/` for static hosting.
const staticExport = process.env.FAULTLINE_STATIC_EXPORT === "1";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  ...(staticExport ? { output: "export" as const, trailingSlash: true } : {}),
};

export default nextConfig;
