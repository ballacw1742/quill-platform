"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/api";

export default function RootPage() {
  const router = useRouter();
  const { data, isLoading } = useSession();

  useEffect(() => {
    if (isLoading) return;
    router.replace(data ? "/queue" : "/login");
  }, [data, isLoading, router]);

  return (
    <main className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
      Loading…
    </main>
  );
}
