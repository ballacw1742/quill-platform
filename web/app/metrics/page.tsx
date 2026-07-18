"use client";

/**
 * /metrics — placeholder scaffold (Lovable redesign links here from home).
 *
 * The Lovable `routes/metrics.tsx` screen will be ported in the module-screen
 * pass. Until then this renders a valid, auth-gated page so the home Metrics
 * tile never 404s. Ported content replaces this file wholesale.
 */

import Link from "next/link";
import { BarChart3 } from "lucide-react";
import { MobileShell } from "@/components/layout/MobileShell";

export default function MetricsPage() {
  return (
    <MobileShell>
      <div className="mx-auto w-full max-w-[708px] px-4 pt-safe md:max-w-4xl md:px-8">
        <header className="pt-6 pb-4">
          <h1 className="text-large-title text-label-primary">Metrics</h1>
          <p className="mt-1 text-subhead text-label-secondary">
            Portfolio metrics — porting from the redesign.
          </p>
        </header>
        <div className="glass rounded-2xl p-6">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-tint text-accent">
            <BarChart3 className="h-6 w-6" aria-hidden />
          </span>
          <p className="mt-4 text-body text-label-primary">
            This screen is scaffolded. The full metrics view is being ported in
            the module pass.
          </p>
          <Link
            href="/today"
            className="mt-4 inline-flex items-center rounded-full bg-accent px-4 py-2 text-callout font-semibold text-white no-tap-highlight active:opacity-80"
          >
            Go to Today
          </Link>
        </div>
      </div>
    </MobileShell>
  );
}
