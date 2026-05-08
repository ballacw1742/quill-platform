"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";

/**
 * MarkdownBody — renders a document's markdown content for the
 * /documents/[id] detail screen.
 *
 * Pipeline:
 *   - GFM via remark-gfm (tables, task lists, strikethrough, autolinks).
 *   - Sanitization via rehype-sanitize using its default schema. This is the
 *     critical safeguard: agent-generated content is never assumed safe; we
 *     strip any inline HTML/scripts before render.
 *
 * Styling: bespoke per element so we can hit the iOS type scale instead of
 * relying on @tailwindcss/typography (which introduces non-token sizes
 * forbidden by DESIGN_SYSTEM \u00a7"Typography"). Headings use text-title-* tokens;
 * body copy uses text-body; code/pre use the iOS-rounded mono fallback.
 */
export function MarkdownBody({
  markdown,
  className,
}: {
  markdown: string;
  className?: string;
}) {
  if (!markdown || markdown.trim().length === 0) {
    return (
      <p className={cn("text-body text-label-secondary", className)}>
        This document has no body yet.
      </p>
    );
  }
  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-title-1 text-label-primary mt-2">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-title-2 text-label-primary mt-2">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-title-3 text-label-primary mt-1">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-headline text-label-primary">{children}</h4>
          ),
          p: ({ children }) => (
            <p className="text-body text-label-primary">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="ml-5 list-disc space-y-1 text-body text-label-primary marker:text-label-tertiary">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="ml-5 list-decimal space-y-1 text-body text-label-primary marker:text-label-tertiary">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="leading-snug">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline underline-offset-2"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-separator/60 pl-4 text-body text-label-secondary italic">
              {children}
            </blockquote>
          ),
          code: ({ children, className: cls }) => {
            // Block code (handled via pre wrapper); inline gets a chip style.
            const isBlock = !!cls;
            if (isBlock) {
              return (
                <code
                  className={cn(
                    "block w-full whitespace-pre-wrap break-words font-mono text-callout",
                    cls,
                  )}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className="rounded-sm bg-bg-elevated px-1 py-0.5 font-mono text-subhead text-label-primary">
                {children}
              </code>
            );
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-md bg-bg-elevated p-3 text-callout text-label-primary">
              {children}
            </pre>
          ),
          hr: () => <hr className="my-2 border-separator/40" />,
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-md border border-separator/40">
              <table className="w-full border-collapse text-callout">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-separator/40 bg-bg-elevated px-3 py-2 text-left text-footnote font-semibold uppercase tracking-wider text-label-secondary">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-separator/40 px-3 py-2 text-label-primary">
              {children}
            </td>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-label-primary">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic text-label-primary">{children}</em>
          ),
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
