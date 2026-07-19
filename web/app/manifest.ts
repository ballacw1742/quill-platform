import type { MetadataRoute } from "next";

/**
 * PWA web app manifest for Quill. Drives the installed/home-screen app name,
 * theme, and icons. Served at /manifest.webmanifest.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Quill",
    short_name: "Quill",
    description:
      "Agentic Infrastructure Management Platform. Agents that research, draft, and execute — every action approval-gated and audit-chained.",
    start_url: "/",
    display: "standalone",
    background_color: "#007AFF",
    theme_color: "#007AFF",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  };
}
