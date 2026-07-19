import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";

/**
 * Quill iOS-redesign — root layout.
 *
 * No web font — the design system mandates the Apple system font stack
 * (-apple-system / SF Pro …) which is set in globals.css and tailwind config.
 * That gives the app native iOS / iPadOS / macOS typography for free; on
 * non-Apple platforms the cascade falls through to system-ui / sans-serif.
 *
 * `viewport-fit=cover` lets safe-area-inset-* notch/home-indicator handling
 * work in mobile Safari.
 */

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FFFFFF" },
    { media: "(prefers-color-scheme: dark)", color: "#000000" },
  ],
};

export const metadata: Metadata = {
  metadataBase: new URL("https://quillpm.com"),
  title: "Quill",
  description: "Agentic Infrastructure Management Platform. Agents that research, draft, and execute — every action approval-gated and audit-chained.",
  applicationName: "Quill",
  openGraph: {
    title: "Quill — Agentic Infrastructure Management Platform",
    description:
      "Agents that research, draft, and execute — every action approval-gated and audit-chained.",
    url: "https://quillpm.com",
    siteName: "Quill",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Quill — Agentic Infrastructure Management Platform",
    description:
      "Agents that research, draft, and execute — every action approval-gated and audit-chained.",
  },
  appleWebApp: {
    capable: true,
    title: "Quill",
    statusBarStyle: "black-translucent",
    // iOS home-screen icon (the branded Quill tile). Without this, saving to
    // the Home Screen shows a generic "Q" screenshot glyph.
    startupImage: [],
  },
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
      { url: "/icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-bg text-label-primary antialiased no-tap-highlight">
        <Providers>
          {children}
          <Toaster
            richColors
            position="bottom-center"
            offset={104}
            closeButton
            toastOptions={{
              classNames: {
                toast:
                  "rounded-xl border border-separator-opaque bg-bg-tertiary text-label-primary shadow-elevated",
              },
            }}
          />
        </Providers>
      </body>
    </html>
  );
}
