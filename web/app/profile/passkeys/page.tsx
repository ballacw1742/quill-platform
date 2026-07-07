"use client";

import * as React from "react";
import { formatDistanceToNow } from "date-fns";
import {
  Fingerprint,
  KeyRound,
  Loader2,
  Plus,
  Smartphone,
  Trash2,
} from "lucide-react";
import { MobileShell, TopBar, BackButton } from "@/components/layout/MobileShell";
import { GroupedList, ListGroup } from "@/components/ui/grouped-list";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { RegisterPasskeyDialog } from "@/components/auth/RegisterPasskeyDialog";
import { SkelList } from "@/components/ui/skeletons";
import {
  isPasskeySupported,
  listPasskeys,
  revokePasskey,
  type PasskeyCredential,
} from "@/lib/auth";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/**
 * /profile/passkeys — replaces /settings/passkeys.
 *
 * iOS Settings-style: grouped list of registered passkeys, each row
 * shows device name + last used. "Add passkey" footer button. Tap a
 * row to bring up the revoke confirmation.
 */

export default function ProfilePasskeysPage() {
  const [credentials, setCredentials] = React.useState<PasskeyCredential[] | null>(
    null,
  );
  const [error, setError] = React.useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const supported = isPasskeySupported();

  const refresh = React.useCallback(async () => {
    setError(null);
    try {
      const list = await listPasskeys();
      setCredentials(list);
    } catch (err) {
      setError(
        err instanceof Error
          ? "Couldn't load your passkeys. Try again."
          : "Couldn't load your passkeys. Try again.",
      );
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onRevoke = async (cred: PasskeyCredential) => {
    if (!confirm(`Revoke "${cred.name ?? "passkey"}"? This can't be undone.`)) return;
    setBusyId(cred.id);
    try {
      await revokePasskey(cred.id);
      toast.success("Passkey revoked");
      await refresh();
    } catch {
      toast.error("Couldn't revoke that passkey. Try again.");
    } finally {
      setBusyId(null);
    }
  };

  const active = credentials?.filter((c) => !c.revoked_at) ?? [];
  const revoked = credentials?.filter((c) => c.revoked_at) ?? [];

  return (
    <MobileShell>
      <TopBar
        title="Passkeys"
        left={<BackButton href="/profile" label="Profile" />}
      />

      <GroupedList>
        {/* Domain-move nudge: quillpm.com is a new WebAuthn RP, so any passkey
            registered before the move is orphaned and must be re-added. We
            can't tell server-side which stored credentials belong to the old
            RP (rp_id isn't stored), so we surface the banner whenever there
            are zero ACTIVE passkeys — the state a just-migrated user lands in. */}
        {credentials !== null && active.length === 0 && supported && (
          <ListGroup>
            <div
              role="status"
              className="px-4 py-3 text-callout text-label-secondary"
            >
              <span className="font-medium text-label-primary">
                Re-register your passkey.
              </span>{" "}
              Quill moved to <span className="font-mono">quillpm.com</span>.
              Passkeys added before the move no longer work and must be added
              again. Until then, you can approve items with your account
              password.
            </div>
          </ListGroup>
        )}

        {!supported && (
          <ListGroup>
            <div className="px-4 py-3 text-callout text-danger">
              Passkeys aren&rsquo;t supported on this browser.
            </div>
          </ListGroup>
        )}

        {error && (
          <ErrorBanner message={error} onRetry={() => refresh()} />
        )}

        {credentials === null && !error && supported && (
          <ListGroup>
            <SkelList
              ariaLabel="Loading passkeys"
              count={2}
              className="rounded-lg overflow-hidden"
            />
          </ListGroup>
        )}

        {credentials !== null && active.length === 0 && supported && (
          <EmptyState
            icon={<Fingerprint />}
            title="No passkeys yet."
            subtitle="Add a passkey to sign in with Face ID or Touch ID."
            action={
              <Button onClick={() => setRegisterOpen(true)} className="rounded-md">
                <Plus className="h-4 w-4" /> Register a passkey
              </Button>
            }
          />
        )}

        {active.length > 0 && (
          <ListGroup
            title="Active"
            footer="Any of these can sign in or authorize an approval."
          >
            {active.map((c, i) => (
              <PasskeyRow
                key={c.id}
                cred={c}
                onRevoke={() => onRevoke(c)}
                busy={busyId === c.id}
                last={i === active.length - 1}
              />
            ))}
          </ListGroup>
        )}

        {revoked.length > 0 && (
          <ListGroup title="Revoked">
            {revoked.map((c, i) => (
              <PasskeyRow
                key={c.id}
                cred={c}
                last={i === revoked.length - 1}
              />
            ))}
          </ListGroup>
        )}

        {credentials !== null && active.length > 0 && supported && (
          <div className="px-4">
            <Button
              onClick={() => setRegisterOpen(true)}
              className="h-[50px] w-full rounded-lg text-headline"
              variant="secondary"
            >
              <Plus className="h-4 w-4" /> Add passkey
            </Button>
          </div>
        )}
      </GroupedList>

      <RegisterPasskeyDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        onRegistered={refresh}
      />
    </MobileShell>
  );
}

function PasskeyRow({
  cred,
  onRevoke,
  busy,
  last,
}: {
  cred: PasskeyCredential;
  onRevoke?: () => void;
  busy?: boolean;
  last?: boolean;
}) {
  const Icon =
    cred.attachment === "cross-platform"
      ? KeyRound
      : cred.transports?.includes("internal")
        ? Fingerprint
        : Smartphone;

  return (
    <div className={cn("relative", cred.revoked_at && "opacity-60")}>
      <div className="flex items-center gap-3 px-4 py-3 min-h-[60px]">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent/10 text-accent">
          <Icon className="h-4 w-4" />
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-headline text-label-primary truncate">
            {cred.name ?? "Passkey"}
          </div>
          <div className="text-footnote text-label-secondary">
            Registered {formatDistanceToNow(new Date(cred.created_at))} ago
            {cred.last_used_at &&
              ` · last used ${formatDistanceToNow(new Date(cred.last_used_at))} ago`}
            {cred.revoked_at && " · revoked"}
          </div>
        </div>
        {onRevoke && (
          <button
            type="button"
            onClick={onRevoke}
            disabled={busy}
            aria-label={`Revoke ${cred.name ?? "passkey"}`}
            className="flex h-11 w-11 items-center justify-center text-danger active:opacity-60 disabled:opacity-30 no-tap-highlight"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
      {!last && (
        <span
          className="pointer-events-none absolute bottom-0 left-[60px] right-0 h-px bg-separator/40"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
