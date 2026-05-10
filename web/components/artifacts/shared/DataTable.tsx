"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  /** Custom class for header + cells. Use `text-right tabular-nums` for numeric cols. */
  className?: string;
  /** Render override for the cell. Header always uses `label`. */
  render?: (row: T) => React.ReactNode;
  /** When true, this column sticks to the left edge during horizontal scroll. Use on the first column only. */
  sticky?: boolean;
  /** Optional explicit min width for the column (e.g. "min-w-[160px]"). */
  minWidth?: string;
}

/**
 * Mobile-first data table that:
 *   • Scrolls horizontally when content exceeds the viewport
 *   • Shows a subtle edge-fade scroll affordance
 *   • Pins the first column (when `sticky: true`) so the row label stays visible
 *   • Uses intrinsic widths (no `min-w-full`) so columns size to their content
 *   • Right-aligns numeric columns automatically via the `tabular-nums` class hint
 */
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
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const [showLeftFade, setShowLeftFade] = React.useState(false);
  const [showRightFade, setShowRightFade] = React.useState(false);

  const updateFades = React.useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const { scrollLeft, scrollWidth, clientWidth } = el;
    setShowLeftFade(scrollLeft > 2);
    setShowRightFade(scrollLeft + clientWidth < scrollWidth - 2);
  }, []);

  React.useEffect(() => {
    updateFades();
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateFades, { passive: true });
    window.addEventListener("resize", updateFades);
    return () => {
      el.removeEventListener("scroll", updateFades);
      window.removeEventListener("resize", updateFades);
    };
  }, [updateFades, rows.length, columns.length]);

  if (rows.length === 0) {
    return (
      <div className="text-callout text-label-tertiary py-3 text-center">
        {emptyText}
      </div>
    );
  }

  return (
    <div className={cn("relative", className)}>
      <div
        ref={scrollRef}
        className={cn(
          // Horizontal scroll container. -mx-4 px-4 pulls scroll edges to the
          // viewport gutters so users can fling past the card padding.
          "overflow-x-auto overscroll-x-contain -mx-4 px-4",
          // iOS-style scroll: smooth, momentum, thin scrollbar.
          "scrollbar-thin",
          // Print: never scroll; show everything.
          "print:overflow-visible print:mx-0 print:px-0",
        )}
        style={{ WebkitOverflowScrolling: "touch" as never }}
      >
        <table className="text-footnote w-max border-separate border-spacing-0 print:w-full">
          <thead>
            <tr>
              {columns.map((col, idx) => (
                <th
                  key={col.key}
                  className={cn(
                    "py-2.5 px-3 text-left text-caption-1 uppercase tracking-wider",
                    "text-label-tertiary font-medium whitespace-nowrap",
                    "border-b border-separator/50 bg-bg",
                    idx === 0 && "pl-0",
                    idx === columns.length - 1 && "pr-0",
                    col.sticky &&
                      "sticky left-0 z-10 bg-bg shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)] print:shadow-none",
                    col.className,
                  )}
                  style={col.minWidth ? undefined : undefined}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rIdx) => (
              <tr
                key={String(row[keyField] ?? rIdx)}
                className="group"
              >
                {columns.map((col, cIdx) => (
                  <td
                    key={col.key}
                    className={cn(
                      "py-3 px-3 text-callout text-label-primary align-top",
                      "border-b border-separator/20",
                      cIdx === 0 && "pl-0",
                      cIdx === columns.length - 1 && "pr-0",
                      col.sticky &&
                        "sticky left-0 z-10 bg-bg group-hover:bg-bg-elevated/40 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)] print:shadow-none",
                      col.minWidth,
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

      {/* Edge fades signal there's more to scroll. Hidden in print. */}
      {showLeftFade && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-6 bg-gradient-to-r from-bg to-transparent print:hidden"
        />
      )}
      {showRightFade && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 w-6 bg-gradient-to-l from-bg to-transparent print:hidden"
        />
      )}
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
