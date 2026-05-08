"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

/**
 * /settings/passkeys → /profile/passkeys redirect.
 *
 * Per MOBILE_UX_SPEC.md §"Tab 4 — Profile" the passkey-management page
 * lives under /profile in the iOS redesign. The old route stays as a
 * permanent redirect so any deep links / bookmarks keep working.
 */
export default function LegacyPasskeysRedirect() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace("/profile/passkeys");
  }, [router]);
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg text-callout text-label-secondary">
      Redirecting…
    </main>
  );
}
