"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  className?: string;
  render?: (row: T) => React.ReactNode;
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  rows,
  keyField,
  className,
  emptyText = "No data",
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  keyField: string;
  className?: string;
  emptyText?: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="text-callout text-label-tertiary py-3 text-center">
        {emptyText}
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto -mx-0", className)}>
      <table className="min-w-full text-footnote">
        <thead>
          <tr className="border-b border-separator/40">
            {columns.map((col) => (
              <th
                key={col.key}
                className={cn(
                  "py-2 pr-3 text-left text-caption-1 uppercase tracking-wider text-label-tertiary font-medium whitespace-nowrap",
                  col.className,
                )}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-separator/20">
          {rows.map((row, i) => (
            <tr
              key={String(row[keyField] ?? i)}
              className="hover:bg-bg-elevated/40"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={cn(
                    "py-2.5 pr-3 text-callout text-label-primary align-top",
                    col.className,
                  )}
                >
                  {col.render
                    ? col.render(row)
                    : (row[col.key] != null
                        ? String(row[col.key])
                        : "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Subtotal row styled consistently with DataTable rows */
export function SubtotalRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex justify-between items-baseline py-2 border-t border-separator/40",
        strong
          ? "text-callout font-semibold text-label-primary"
          : "text-callout text-label-secondary",
      )}
    >
      <span>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
