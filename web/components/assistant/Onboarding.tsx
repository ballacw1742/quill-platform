"use client";

/**
 * Onboarding — first-run / empty-state for a new tenant (Phase E).
 *
 * Light, reuse-first: a compact card set that mirrors ONBOARDING.md Part 1
 * (what's an agent, the 3 templates, pairing a channel, how approvals work)
 * with deep links into the existing surfaces. Shown on the /assistant empty
 * state when the tenant has no conversations yet. Read-only guidance — it
 * never mutates anything.
 */

import * as React from "react";
import { Bot, Layers, Link2, ShieldCheck, Sparkles } from "lucide-react";

/** The 3 starter templates (AGENT_BUILDER.md §6 — kept in sync with the
 * server templates; this is copy only, the builder fetches the real list). */
export const ONBOARDING_TEMPLATES: { name: string; summary: string }[] = [
  { name: "Research Assistant", summary: "Gathers, summarizes, organizes. Memory on." },
  { name: "Ops Analyst", summary: "Structured analysis over your data." },
  { name: "Project Copilot", summary: "Hands-on project help; pairs with approvals." },
];

/** Ordered onboarding steps (mirrors ONBOARDING.md Part 1). Exported for a
 * pure render test. */
export const ONBOARDING_STEPS: {
  key: string;
  title: string;
  body: string;
  href?: string;
  cta?: string;
}[] = [
  {
    key: "agent",
    title: "What's an agent?",
    body: "A saved assistant: a prompt + model + curated tools + a monthly budget. You start with Personal (memory on) and Quill (portfolio reads).",
  },
  {
    key: "templates",
    title: "Build from a template",
    body: "Start from Research Assistant, Ops Analyst, or Project Copilot instead of a blank prompt.",
    href: "/assistant/builder",
    cta: "Open Agent Builder",
  },
  {
    key: "channels",
    title: "Pair a channel",
    body: "Reach an agent from Telegram or Google Chat with a single-use pairing code.",
    href: "/assistant/channels",
    cta: "Link a channel",
  },
  {
    key: "approvals",
    title: "How approvals work",
    body: "Agents never write on their own — they queue an approval for a human. Injection can't do anything unapproved.",
  },
];

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  agent: Bot,
  templates: Layers,
  channels: Link2,
  approvals: ShieldCheck,
};

export function Onboarding({ personal }: { personal: boolean }) {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 px-6 pt-10">
      <div className="flex flex-col items-center gap-2 text-center">
        <Sparkles className="h-8 w-8 text-accent" aria-hidden="true" />
        <h2 className="text-title-3 font-semibold text-label-primary">
          Welcome to Agent Cloud
        </h2>
        <p className="text-footnote text-label-secondary">
          {personal
            ? "Your personal assistant remembers what matters across conversations. Here's how to get the most out of it."
            : "Ask about the Quill portfolio — finance, pipeline, operations, customers, approvals."}
        </p>
      </div>

      <div className="mt-2 flex flex-col gap-2">
        {ONBOARDING_STEPS.map((s) => {
          const Icon = ICONS[s.key] ?? Sparkles;
          return (
            <div
              key={s.key}
              className="rounded-xl border border-separator bg-chrome px-4 py-3"
            >
              <div className="flex items-start gap-3">
                <Icon className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="text-body font-medium text-label-primary">{s.title}</p>
                  <p className="mt-0.5 text-footnote text-label-secondary">{s.body}</p>
                  {s.href && (
                    <a
                      href={s.href}
                      className="mt-1 inline-block text-footnote font-medium text-accent active:opacity-60 no-tap-highlight"
                    >
                      {s.cta} →
                    </a>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-1 text-center text-caption-1 text-label-tertiary">
        Or just type below to start chatting.
      </p>
    </div>
  );
}
