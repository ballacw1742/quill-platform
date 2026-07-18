"use client";

import * as React from "react";
import Link from "next/link";
import { CheckCircle, XCircle, Loader2, Paperclip, MinusCircle, GitPullRequest } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ProjectRequest } from "@/lib/schemas";

/**
 * RequestBubble — renders a single user-submitted project request.
 *
 * Layout: right-aligned (user message), with:
 *   - message text
 *   - file name chips (if any)
 *   - status badge
 *   - link to output module (if complete)
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

function moduleHref(module: string | null | undefined, outputId: string | null | undefined): string | null {
  if (!module) return null;
  const routes: Record<string, string> = {
    estimates: "/estimates",
    schedules: "/estimates",  // schedules live under estimates
    rfi: "/queue",
    contracts: "/contracts",
    projects: "/projects",
  };
  const base = routes[module];
  if (!base) return null;
  return outputId ? `${base}/${outputId}` : base;
}

function StatusBadge({ status, intent, outputModule, outputId, deliverableHitlKind, deliverableStatus }: {
  status: string;
  intent: string;
  outputModule?: string | null;
  outputId?: string | null;
  deliverableHitlKind?: string | null;
  deliverableStatus?: string | null;
}) {
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-caption-2 text-warning">
        <Loader2 className="h-3 w-3 animate-spin" />
        Processing…
      </span>
    );
  }

  if (status === "complete") {
    // Phase G4: co-development gate — deliverable is awaiting_human with a
    // co_development hitl kind. Show a distinct badge pointing to the
    // Deliverables tab (where the DeliverableDetailSheet can be opened).
    if (
      deliverableHitlKind === "co_development" &&
      deliverableStatus === "awaiting_human"
    ) {
      return (
        <Link
          href="/projects"
          className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-caption-2 text-accent underline-offset-2 hover:underline"
          title="Open your project's Deliverables tab to co-develop this item with AI"
        >
          <GitPullRequest className="h-3 w-3" />
          Awaiting your input — co-develop
        </Link>
      );
    }

    const href = moduleHref(outputModule, outputId);
    const label = outputModule
      ? `Complete — view in ${outputModule.charAt(0).toUpperCase() + outputModule.slice(1)}`
      : "Complete";
    return href ? (
      <Link
        href={href}
        className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-caption-2 text-success underline-offset-2 hover:underline"
      >
        <CheckCircle className="h-3 w-3" />
        {label}
      </Link>
    ) : (
      <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-caption-2 text-success">
        <CheckCircle className="h-3 w-3" />
        {label}
      </span>
    );
  }

  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-2 py-0.5 text-caption-2 text-danger">
        <XCircle className="h-3 w-3" />
        Failed
      </span>
    );
  }

  // Modular Framework Phase 2: the owning module is turned off, so the request
  // was skipped rather than dispatched. Neutral badge — not an error.
  if (status === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-label-tertiary/10 px-2 py-0.5 text-caption-2 text-label-secondary">
        <MinusCircle className="h-3 w-3" />
        Skipped — module off
      </span>
    );
  }

  return null;
}

export function RequestBubble({ request }: { request: ProjectRequest }) {
  const fileNames = request.filenames
    ? request.filenames.split(",").filter(Boolean)
    : [];

  return (
    <div className="flex justify-end mb-3 px-4">
      <div className="max-w-[80%] space-y-1.5">
        {/* Message bubble */}
        <div className="rounded-2xl rounded-br-sm bg-accent/20 px-4 py-3">
          <p className="text-body text-label-primary whitespace-pre-wrap break-words">
            {request.message}
          </p>

          {/* File chips */}
          {fileNames.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {fileNames.map((name) => (
                <span
                  key={name}
                  className="inline-flex items-center gap-1 rounded-full bg-bg-elevated px-2 py-0.5 text-caption-2 text-label-secondary"
                >
                  <Paperclip className="h-3 w-3" />
                  {name}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Status badge + intent */}
        <div className="flex items-center justify-end gap-2">
          <span className="text-caption-2 text-label-tertiary">
            {intentIcon(request.intent)}{" "}
            {new Date(
              /[Zz]|[+-]\d{2}:\d{2}$/.test(request.created_at)
                ? request.created_at
                : request.created_at + "Z"
            ).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
          </span>
          <StatusBadge
            status={request.status}
            intent={request.intent}
            outputModule={request.output_module}
            outputId={request.output_id}
            deliverableHitlKind={request.deliverable_hitl_kind}
            deliverableStatus={request.deliverable_status}
          />
        </div>
      </div>
    </div>
  );
}
