"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

/**
 * MarkdownBlock — safely renders markdown content.
 * Uses react-markdown + rehype-sanitize; no dangerouslySetInnerHTML.
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
        "[&_table]:w-full [&_table]:text-footnote",
        "[&_th]:text-left [&_th]:text-caption-1 [&_th]:uppercase [&_th]:tracking-wider [&_th]:text-label-tertiary [&_th]:pb-2",
        "[&_td]:py-1.5 [&_td]:pr-2 [&_td]:text-callout [&_td]:text-label-primary",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
