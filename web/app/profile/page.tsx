"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  Bot,
  ChevronRight,
  Fingerprint,
  Info,
  LogOut,
  Send,
  Settings as SettingsIcon,
  User as UserIcon,
} from "lucide-react";
import { MobileShell, TopBar } from "@/components/layout/MobileShell";
import { GroupedList, ListGroup } from "@/components/ui/grouped-list";
import { ListRow } from "@/components/ui/list-row";
import { useLogout, useSession } from "@/lib/api";
import type { Session } from "@/lib/schemas";
import { toast } from "sonner";
import { SkelBar } from "@/components/ui/skeletons";

/**
 * /profile — iOS-redesign profile + admin landing.
 *
 * MOBILE_UX_SPEC.md §"Tab 4 — Profile":
 *   Section 1 — Account: name, email, role chip
 *   Section 2 — Authentication: passkeys, sign out (danger)
 *   Section 3 — Telegram: paired bot + chat id, or 'Pair Telegram'
 *   Section 4 — Quill (advanced): agents, fleet health, settings, about
 */

export default function ProfilePage() {
  const router = useRouter();
  const { data: rawSession, isLoading: sessionLoading } = useSession();
  const session = rawSession as Session | null | undefined;
  const logout = useLogout();
  const showSessionSkel = sessionLoading && !session;

  const onSignOut = () => {
    if (!confirm("Sign out of Quill?")) return;
    logout.mutate(undefined, {
      onSuccess: () => {
        toast.success("Signed out");
        router.replace("/login");
      },
    });
  };

  return (
    <MobileShell>
      <TopBar
        hero
        title="Profile"
        subtitle={
          showSessionSkel ? (
            <SkelBar tone="dark" className="h-4 w-40 inline-block align-middle" />
          ) : (
            session?.email ?? "Not signed in"
          )
        }
      />

      <GroupedList>
        <ListGroup title="Account">
          {showSessionSkel ? (
            <div
              className="flex items-center gap-3 px-4 py-3 min-h-[56px]"
              role="status"
              aria-busy="true"
              aria-label="Loading account"
            >
              <SkelBar className="h-7 w-7 shrink-0 rounded-md" />
              <div className="flex-1 space-y-1.5">
                <SkelBar className="h-4 w-2/3" />
                <SkelBar className="h-3.5 w-5/6" />
              </div>
              <SkelBar className="h-3 w-12 shrink-0" />
            </div>
          ) : (
            <ListRow
              icon={<UserIcon className="h-4 w-4" />}
              iconTone="accent"
              title={session?.display_name ?? session?.email ?? "—"}
              subtitle={session?.email ?? undefined}
              chip={String(session?.role ?? "viewer")}
              chevron={false}
              hideDivider
            />
          )}
        </ListGroup>

        <ListGroup title="Authentication">
          <ListRow
            icon={<Fingerprint className="h-4 w-4" />}
            iconTone="accent"
            title="Passkeys"
            subtitle="Manage devices and security keys"
            href="/profile/passkeys"
          />
          <button
            type="button"
            onClick={onSignOut}
            className="block w-full text-left no-tap-highlight active:bg-bg-elevated/60"
          >
            <div className="flex items-center gap-3 px-4 py-3 min-h-[56px]">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-danger/10 text-danger">
                <LogOut className="h-4 w-4" />
              </span>
              <div className="flex-1">
                <div className="text-headline text-danger">Sign out</div>
              </div>
            </div>
          </button>
        </ListGroup>

        <ListGroup
          title="Telegram"
          footer={
            session?.telegram_chat_id
              ? "Quill posts your daily brief and approval pings here."
              : "Pair to receive daily briefs and approval pings."
          }
        >
          {session?.telegram_chat_id ? (
            <ListRow
              icon={<Send className="h-4 w-4" />}
              iconTone="info"
              title="Telegram"
              subtitle={`Paired · chat ${session.telegram_chat_id}`}
              chevron={false}
              hideDivider
            />
          ) : (
            <ListRow
              icon={<Send className="h-4 w-4" />}
              iconTone="info"
              title="Pair Telegram"
              subtitle="Link your Telegram chat to Quill"
              onClick={() => {
                toast.message(
                  "DM @DC_QuillBot the command shown in your terminal to pair.",
                );
              }}
              hideDivider
            />
          )}
        </ListGroup>

        <ListGroup title="Quill">
          <ListRow
            icon={<Bot className="h-4 w-4" />}
            iconTone="info"
            title="Agents"
            subtitle="Fleet status, trust tiers, budgets"
            href="/profile/agents"
          />
          <ListRow
            icon={<Activity className="h-4 w-4" />}
            iconTone="success"
            title="Fleet health"
            subtitle="Subsystems, queue depth, spend"
            href="/profile/health"
          />
          <ListRow
            icon={<Activity className="h-4 w-4" />}
            iconTone="info"
            title="Activity"
            subtitle="Tamper-proof record of every action"
            href="/audit"
          />
          <ListRow
            icon={<SettingsIcon className="h-4 w-4" />}
            iconTone="neutral"
            title="Settings"
            subtitle="Account, appearance, app info"
            href="/settings"
          />
          <ListRow
            icon={<Info className="h-4 w-4" />}
            iconTone="neutral"
            title="About Quill"
            subtitle="Version, build, links"
            onClick={() =>
              toast.message(
                `Quill web · build ${process.env.NEXT_PUBLIC_BUILD_ID ?? "dev"}`,
              )
            }
            hideDivider
          />
        </ListGroup>

        <div className="px-4 pt-2 pb-12 text-center text-footnote text-label-tertiary">
          Quill — Approval queue for the Agentic PMO fleet
        </div>
      </GroupedList>
    </MobileShell>
  );
}
