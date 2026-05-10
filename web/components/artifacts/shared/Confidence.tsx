"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

type ConfidenceLevel = "high" | "medium" | "low";

function toLevel(confidence: number): ConfidenceLevel {
  if (confidence >= 0.75) return "high";
  if (confidence >= 0.5) return "medium";
  return "low";
}

const levelStyles: Record<ConfidenceLevel, string> = {
  high: "bg-success/15 text-success",
  medium: "bg-warning/15 text-warning",
  low: "bg-danger/15 text-danger",
};

const levelLabels: Record<ConfidenceLevel, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

export function ConfidenceBadge({
  confidence,
  className,
}: {
  confidence: number;
  className?: string;
}) {
  const level = toLevel(confidence);
  const pct = Math.round(confidence * 100);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-footnote font-medium",
        levelStyles[level],
        className,
      )}
      title={levelLabels[level]}
    >
      {pct}%
    </span>
  );
}
