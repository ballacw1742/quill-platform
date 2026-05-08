"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

/** /health → /profile/health redirect (iOS-redesign moves this under Profile). */
export default function LegacyHealthRedirect() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace("/profile/health");
  }, [router]);
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg text-callout text-label-secondary">
      Redirecting…
    </main>
  );
}
