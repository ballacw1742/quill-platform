"use client";

import * as React from "react";
import { formatDistanceToNow } from "date-fns";
import {
  Fingerprint,
  KeyRound,
  Loader2,
  Plus,
  ShieldCheck,
  Smartphone,
  Trash2,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { RegisterPasskeyDialog } from "@/components/auth/RegisterPasskeyDialog";
import {
  isPasskeySupported,
  listPasskeys,
  revokePasskey,
  type PasskeyCredential,
} from "@/lib/auth";
import { toast } from "sonner";

export default function PasskeysPage() {
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
      setError(err instanceof Error ? err.message : "Failed to load passkeys");
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const onRevoke = async (cred: PasskeyCredential) => {
    if (!confirm(`Revoke "${cred.name ?? "passkey"}"? This can't be undone.`)) {
      return;
    }
    setBusyId(cred.id);
    try {
      await revokePasskey(cred.id);
      toast.success("Passkey revoked");
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusyId(null);
    }
  };

  const active = credentials?.filter((c) => !c.revoked_at) ?? [];
  const revoked = credentials?.filter((c) => c.revoked_at) ?? [];

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-6 p-6">
        <header className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <ShieldCheck className="h-5 w-5 text-primary" /> Passkeys
            </h1>
            <p className="text-sm text-muted-foreground">
              Manage the devices and security keys that can sign you in and
              approve actions.
            </p>
          </div>
          <Button
            onClick={() => setRegisterOpen(true)}
            disabled={!supported}
            title={
              supported
                ? "Register a new passkey"
                : "WebAuthn not supported on this browser"
            }
          >
            <Plus className="h-4 w-4" /> Register
          </Button>
        </header>

        {!supported && (
          <Alert variant="destructive">
            <AlertDescription>
              Passkeys aren’t supported on this browser. Use Safari, Chrome,
              Edge, or Firefox on a device with biometrics or a security key.
            </AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Active passkeys</CardTitle>
            <CardDescription>
              Any of these can sign in or authorize an approval.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {credentials === null && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </div>
            )}
            {credentials !== null && active.length === 0 && (
              <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
                No passkeys yet. Register one to get started.
              </div>
            )}
            {active.map((c) => (
              <PasskeyRow
                key={c.id}
                cred={c}
                onRevoke={() => onRevoke(c)}
                busy={busyId === c.id}
              />
            ))}
          </CardContent>
        </Card>

        {revoked.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Revoked</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 opacity-70">
              {revoked.map((c) => (
                <PasskeyRow key={c.id} cred={c} />
              ))}
            </CardContent>
          </Card>
        )}

        <Alert variant="default" className="text-xs">
          <AlertDescription>
            Lost your passkey? Contact Charles. Recovery is a manual,
            audit-logged step.
          </AlertDescription>
        </Alert>
      </div>

      <RegisterPasskeyDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        onRegistered={refresh}
      />
    </AppShell>
  );
}

function PasskeyRow({
  cred,
  onRevoke,
  busy,
}: {
  cred: PasskeyCredential;
  onRevoke?: () => void;
  busy?: boolean;
}) {
  const Icon = cred.attachment === "cross-platform" ? KeyRound : cred.transports?.includes("internal") ? Fingerprint : Smartphone;
  return (
    <div className="flex items-center justify-between rounded-md border p-3">
      <div className="flex items-center gap-3">
        <Icon className="h-5 w-5 text-primary" />
        <div className="min-w-0">
          <div className="truncate font-medium">{cred.name ?? "Passkey"}</div>
          <div className="text-xs text-muted-foreground">
            Registered {formatDistanceToNow(new Date(cred.created_at))} ago
            {cred.last_used_at &&
              ` · last used ${formatDistanceToNow(new Date(cred.last_used_at))} ago`}
            {cred.revoked_at && ` · revoked`}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {cred.attachment && (
              <Badge variant="secondary" className="text-[10px]">
                {cred.attachment === "platform"
                  ? "Platform"
                  : cred.attachment === "cross-platform"
                    ? "Security key"
                    : cred.attachment}
              </Badge>
            )}
            {cred.backup_eligible && (
              <Badge variant="secondary" className="text-[10px]">
                Synced
              </Badge>
            )}
            {cred.transports && (
              <Badge variant="outline" className="text-[10px]">
                {cred.transports}
              </Badge>
            )}
          </div>
        </div>
      </div>
      {onRevoke && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onRevoke}
          disabled={busy}
          className="text-destructive"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
          Revoke
        </Button>
      )}
    </div>
  );
}
