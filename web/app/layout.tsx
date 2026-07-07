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
  description: "AI-native project management. Agents that research, draft, and execute — every action approval-gated and audit-chained.",
  applicationName: "Quill",
  openGraph: {
    title: "Quill — AI-native project management",
    description:
      "Agents that research, draft, and execute — every action approval-gated and audit-chained.",
    url: "https://quillpm.com",
    siteName: "Quill",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Quill — AI-native project management",
    description:
      "Agents that research, draft, and execute — every action approval-gated and audit-chained.",
  },
  appleWebApp: {
    capable: true,
    title: "Quill",
    statusBarStyle: "black-translucent",
  },
  icons: { icon: "/favicon.ico" },
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
