"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProjectRequest } from "@/lib/schemas";

/**
 * ResponseBubble — renders the agent response for a completed request.
 *
 * Only rendered when status === "complete" and response is non-empty.
 * Left-aligned (agent response style).
 */

function intentIcon(intent: string): string {
  const icons: Record<string, string> = {
    estimate: "💰",
    schedule: "📅",
    rfi: "📋",
    contract: "📄",
    general: "🤖",
  };
  return icons[intent] ?? "🤖";
}

function intentLabel(intent: string): string {
  const labels: Record<string, string> = {
    estimate: "Estimator",
    schedule: "Scheduler",
    rfi: "RFI Agent",
    contract: "Contract Reviewer",
    general: "Coordinator",
  };
  return labels[intent] ?? "Agent";
}

function moduleHref(module: string | null | undefined, outputId: string | null | undefined): string | null {
  if (!module) return null;
  const routes: Record<string, string> = {
    estimates: "/estimates",
    schedules: "/estimates",
    rfi: "/queue",
    contracts: "/contracts",
  };
  const base = routes[module];
  if (!base) return null;
  return outputId ? `${base}/${outputId}` : base;
}

export function ResponseBubble({ request }: { request: ProjectRequest }) {
  if (request.status !== "complete" || !request.response) return null;

  const href = moduleHref(request.output_module, request.output_id);

  return (
    <div className="mb-3 flex justify-start px-4">
      <div className="max-w-[80%] space-y-1.5">
        <div className="ml-1 flex items-center gap-1.5 text-caption-1 text-label-tertiary">
          <span aria-hidden>{intentIcon(request.intent)}</span>
          <span>{intentLabel(request.intent)}</span>
        </div>

        {/* Response bubble */}
        <div className="rounded-2xl rounded-bl-sm bg-bg-elevated px-4 py-3">
          <p className="text-body text-label-primary whitespace-pre-wrap break-words">
            {request.response}
          </p>

          {/* View result link */}
          {href && (
            <Link
              href={href}
              className="mt-2 inline-flex items-center gap-1 text-caption-1 text-accent underline-offset-2 hover:underline"
            >
              View result
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}
        </div>

        <div className="ml-1 text-caption-2 text-label-tertiary">
          {new Date(
            /[Zz]|[+-]\d{2}:\d{2}$/.test(request.updated_at)
              ? request.updated_at
              : request.updated_at + "Z"
          ).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
        </div>
      </div>
    </div>
  );
}
