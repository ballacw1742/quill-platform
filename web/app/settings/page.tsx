"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  Info,
  LogOut,
  Mail,
  Moon,
  ShieldCheck,
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
 * /settings — dedicated iOS grouped-list settings screen (UI_REDESIGN_BRIEF
 * §3 avatar menu, Phase 4). Account details from the session endpoint,
 * appearance note (follows system), sign out, app version. No new backend
 * endpoints.
 */
export default function SettingsPage() {
  const router = useRouter();
  const { data: rawSession, isLoading: sessionLoading } = useSession();
  const session = rawSession as Session | null | undefined;
  const logout = useLogout();
  const showSkel = sessionLoading && !session;

  const version = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";

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
      <TopBar hero title="Settings" subtitle="Account, appearance & app info" />

      <GroupedList>
        <ListGroup title="Account">
          {showSkel ? (
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
            </div>
          ) : (
            <>
              <ListRow
                icon={<UserIcon className="h-4 w-4" />}
                iconTone="accent"
                title={session?.display_name ?? session?.email ?? "—"}
                subtitle="Name"
                chevron={false}
              />
              <ListRow
                icon={<Mail className="h-4 w-4" />}
                iconTone="info"
                title={session?.email ?? "—"}
                subtitle="Email"
                chevron={false}
              />
              <ListRow
                icon={<ShieldCheck className="h-4 w-4" />}
                iconTone="success"
                title={String(session?.role ?? "viewer")}
                subtitle="Role"
                chevron={false}
                hideDivider
              />
            </>
          )}
        </ListGroup>

        <ListGroup
          title="Appearance"
          footer="Quill follows your device's light or dark appearance automatically."
        >
          <ListRow
            icon={<Moon className="h-4 w-4" />}
            iconTone="neutral"
            title="Appearance"
            subtitle="Follows system setting"
            chevron={false}
            hideDivider
          />
        </ListGroup>

        <ListGroup title="Session">
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

        <ListGroup title="About">
          <ListRow
            icon={<Info className="h-4 w-4" />}
            iconTone="neutral"
            title="Version"
            subtitle={`Quill web · build ${version}`}
            chevron={false}
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
