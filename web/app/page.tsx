"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";

export default function RootPage() {
  const router = useRouter();
  const { data: rawData, isLoading } = useSession();
  const data = rawData as Session | null | undefined;

  useEffect(() => {
    if (isLoading) return;
    router.replace(data ? "/queue" : "/login");
  }, [data, isLoading, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-bg text-callout text-label-secondary" />
  );
}
