"use client";

import * as React from "react";
import { AlertCircle, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * ErrorBoundary — top-level, blocking error surface for an entire module
 * subtree (Sprint 5.3). When a render/lifecycle error escapes a page's tree,
 * this catches it, logs it to the console (no external service), and renders a
 * clean centered fallback card instead of a blank/white screen.
 *
 * Visuals (per DESIGN_SYSTEM, matching ErrorBanner tokens):
 *   - Card on bg-tertiary with a danger accent
 *   - label-secondary message text
 *   - "Try again" pill that resets state so the subtree re-renders
 */
interface ErrorBoundaryProps {
  moduleName: string;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    console.error(
      `[ErrorBoundary] "${this.props.moduleName}" module crashed:`,
      error,
      errorInfo,
    );
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: undefined });
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-[60vh] w-full items-center justify-center p-6">
          <div
            role="alert"
            aria-live="polite"
            className={cn(
              "flex w-full max-w-sm flex-col items-center gap-4 rounded-xl bg-bg-tertiary p-6 text-center",
              "border-l-[3px] border-danger",
            )}
          >
            <AlertCircle
              className="h-8 w-8 shrink-0 text-danger"
              aria-hidden="true"
            />
            <div className="flex flex-col gap-1">
              <div className="text-caption font-medium uppercase tracking-wide text-label-tertiary">
                {this.props.moduleName}
              </div>
              <div className="text-body font-semibold text-label-primary">
                Something went wrong
              </div>
              <div className="text-callout text-label-secondary leading-snug">
                This section ran into an unexpected problem. You can try loading
                it again.
              </div>
            </div>
            <button
              type="button"
              onClick={this.handleReset}
              className={cn(
                "inline-flex items-center gap-1 shrink-0 rounded-md px-4 py-2",
                "text-callout font-medium text-accent active:opacity-60 no-tap-highlight",
                "min-h-[36px]",
              )}
            >
              <RotateCw className="h-4 w-4" aria-hidden="true" />
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
