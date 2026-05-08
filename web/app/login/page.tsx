"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Fingerprint, KeyRound, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useLogin, useSession } from "@/lib/api";
import {
  isPasskeySupported,
  isUserCancelledError,
  loginWithPasskey,
} from "@/lib/auth";
import { RegisterPasskeyDialog } from "@/components/auth/RegisterPasskeyDialog";
import { toast } from "sonner";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

const DEV_FALLBACK =
  typeof process !== "undefined" &&
  process.env.NEXT_PUBLIC_DEV_AUTH_FALLBACK === "1";

export default function LoginPage() {
  const router = useRouter();
  const { data: session } = useSession();
  const passwordLogin = useLogin();
  const passkeyAvailable = isPasskeySupported();

  const [passkeyPending, setPasskeyPending] = React.useState(false);
  const [registerOpen, setRegisterOpen] = React.useState(false);

  React.useEffect(() => {
    if (session) router.replace("/queue");
  }, [session, router]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "charles@monarktechnology.com", password: "" },
  });

  const onPasskey = async () => {
    const email = form.getValues("email");
    if (!email) {
      form.setError("email", { message: "Email required for passkey" });
      return;
    }
    setPasskeyPending(true);
    try {
      const result = await loginWithPasskey(email);
      if (typeof window !== "undefined") {
        window.localStorage.setItem("quill.session", JSON.stringify(result));
      }
      toast.success("Signed in with passkey");
      router.replace("/queue");
    } catch (err) {
      if (isUserCancelledError(err)) {
        toast.message("Passkey prompt cancelled");
      } else {
        toast.error(
          err instanceof Error ? err.message : "Passkey sign-in failed",
        );
      }
    } finally {
      setPasskeyPending(false);
    }
  };

  const onPassword = (values: FormValues) => {
    if (!values.password) {
      form.setError("password", { message: "Required" });
      return;
    }
    passwordLogin.mutate(
      { email: values.email, password: values.password },
      {
        onSuccess: () => {
          toast.success("Signed in");
          router.replace("/queue");
        },
        onError: (e) => toast.error(e.message || "Sign-in failed"),
      },
    );
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-b from-slate-50 to-slate-100 p-4 dark:from-slate-950 dark:to-slate-900">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck className="h-6 w-6 text-primary" />
            <span className="text-lg font-semibold tracking-tight">Quill</span>
          </div>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            Approval queue for the Agentic PMO fleet.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onPassword)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                autoComplete="username webauthn"
                {...form.register("email")}
              />
              {form.formState.errors.email && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.email.message}
                </p>
              )}
            </div>

            <Button
              type="button"
              className="w-full"
              onClick={onPasskey}
              disabled={!passkeyAvailable || passkeyPending}
            >
              <Fingerprint className="h-4 w-4" />
              {passkeyPending ? "Waiting for passkey…" : "Sign in with passkey"}
            </Button>

            {!passkeyAvailable && (
              <Alert variant="default" className="text-xs">
                <AlertDescription>
                  Passkeys aren’t supported on this browser. Use Safari, Chrome,
                  Edge, or Firefox on a modern device.
                </AlertDescription>
              </Alert>
            )}

            <button
              type="button"
              onClick={() => setRegisterOpen(true)}
              className="w-full text-center text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              First time on this device? Register a passkey →
            </button>

            {DEV_FALLBACK && (
              <details className="rounded-md border bg-muted/30 p-3 text-xs">
                <summary className="flex cursor-pointer items-center gap-2 text-muted-foreground">
                  <KeyRound className="h-3.5 w-3.5" /> Dev: email + password
                </summary>
                <div className="mt-3 space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="password">Password</Label>
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      {...form.register("password")}
                    />
                  </div>
                  <Button
                    type="submit"
                    variant="outline"
                    className="w-full"
                    disabled={passwordLogin.isPending}
                  >
                    {passwordLogin.isPending ? "Signing in…" : "Sign in (dev)"}
                  </Button>
                </div>
              </details>
            )}
          </form>
        </CardContent>
      </Card>

      <RegisterPasskeyDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
      />
    </main>
  );
}
