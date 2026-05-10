"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

/**
 * MarkdownBlock — safely renders markdown content.
 * Uses react-markdown + rehype-sanitize; no dangerouslySetInnerHTML.
 *
 * Tables get a mobile-friendly horizontal-scroll wrapper so wide tables
 * don't squish into the viewport. First column is visually pinned so the
 * row label stays in view while you swipe.
 */
export function MarkdownBlock({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  if (!content) return null;

  return (
    <div
      className={cn(
        "prose prose-sm max-w-none text-label-primary",
        // Override prose defaults to use our iOS color tokens
        "[&_h1]:text-title-3 [&_h1]:text-label-primary [&_h1]:font-semibold [&_h1]:mt-4 [&_h1]:mb-2",
        "[&_h2]:text-headline [&_h2]:text-label-primary [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2",
        "[&_h3]:text-callout [&_h3]:text-label-primary [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1",
        "[&_p]:text-callout [&_p]:text-label-primary [&_p]:leading-relaxed [&_p]:mb-3",
        "[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1",
        "[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:space-y-1",
        "[&_li]:text-callout [&_li]:text-label-primary [&_li]:leading-relaxed",
        "[&_strong]:font-semibold [&_strong]:text-label-primary",
        "[&_em]:italic [&_em]:text-label-secondary",
        "[&_code]:font-mono [&_code]:text-footnote [&_code]:bg-bg-elevated [&_code]:px-1 [&_code]:rounded",
        "[&_pre]:bg-bg-elevated [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:overflow-x-auto",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-accent/40 [&_blockquote]:pl-3 [&_blockquote]:text-label-secondary [&_blockquote]:italic",
        "[&_hr]:border-separator/40 [&_hr]:my-4",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          // Tables get wrapped in a mobile-friendly horizontal-scroll container.
          // Use w-max + border-separate so columns intrinsically size to their
          // content instead of being squished into the viewport.
          table: ({ node: _node, ...props }) => (
            <ScrollableTable {...props} />
          ),
          thead: ({ node: _node, ...props }) => (
            <thead {...props} />
          ),
          tbody: ({ node: _node, ...props }) => (
            <tbody {...props} />
          ),
          th: ({ node: _node, className, ...props }) => (
            <th
              {...props}
              className={cn(
                "text-left text-caption-1 uppercase tracking-wider text-label-tertiary",
                "font-medium py-2.5 px-3 whitespace-nowrap",
                "border-b border-separator/50 bg-bg",
                className,
              )}
            />
          ),
          td: ({ node: _node, className, ...props }) => (
            <td
              {...props}
              className={cn(
                "py-3 px-3 text-callout text-label-primary align-top",
                "border-b border-separator/20",
                "whitespace-normal",
                className,
              )}
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Wraps a <table> in a horizontal-scroll container with sticky first column
 * and edge fades. Pure CSS — the first cell of every row sticks to the left.
 */
function ScrollableTable(props: React.HTMLAttributes<HTMLTableElement>) {
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
  }, [updateFades]);

  return (
    <div className="relative not-prose my-3">
      <div
        ref={scrollRef}
        className={cn(
          "overflow-x-auto overscroll-x-contain -mx-4 px-4 scrollbar-thin",
          "print:overflow-visible print:mx-0 print:px-0",
        )}
        style={{ WebkitOverflowScrolling: "touch" as never }}
      >
        <table
          {...props}
          className={cn(
            "w-max text-footnote border-separate border-spacing-0 print:w-full",
            // Pin first column. Class hooks via :first-child selectors.
            "[&_th:first-child]:sticky [&_th:first-child]:left-0 [&_th:first-child]:z-10 [&_th:first-child]:bg-bg",
            "[&_th:first-child]:shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)] print:[&_th:first-child]:shadow-none",
            "[&_td:first-child]:sticky [&_td:first-child]:left-0 [&_td:first-child]:z-10 [&_td:first-child]:bg-bg",
            "[&_td:first-child]:shadow-[2px_0_4px_-2px_rgba(0,0,0,0.06)] print:[&_td:first-child]:shadow-none",
            "[&_td:first-child]:min-w-[160px] [&_td:first-child]:max-w-[260px]",
            "[&_th:first-child]:min-w-[160px]",
            props.className,
          )}
        />
      </div>
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
