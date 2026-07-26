/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — FastAPI serves the built files on Databricks Apps
  output: 'export',
  trailingSlash: true,

  images: {
    // Required for static export (no Next.js image optimisation server)
    unoptimized: true,
  },

  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || '',
  },
}
module.exports = nextConfig
