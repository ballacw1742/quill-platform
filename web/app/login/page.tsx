"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Fingerprint, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useLogin, useSession } from "@/lib/api";
import { isPasskeySupported } from "@/lib/auth";
import { toast } from "sonner";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Required"),
});
type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const { data: session } = useSession();
  const login = useLogin();
  const passkeyAvailable = isPasskeySupported();

  React.useEffect(() => {
    if (session) router.replace("/queue");
  }, [session, router]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "charles@monarktechnology.com", password: "" },
  });

  const onSubmit = (values: FormValues) => {
    login.mutate(values, {
      onSuccess: () => {
        toast.success("Signed in");
        router.replace("/queue");
      },
      onError: (e) => toast.error(e.message || "Sign-in failed"),
    });
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
          <CardDescription>Approval queue for the Agentic PMO fleet.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" autoComplete="email" {...form.register("email")} />
              {form.formState.errors.email && (
                <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...form.register("password")}
              />
              {form.formState.errors.password && (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled
              title={passkeyAvailable ? "WebAuthn wiring lands in Sprint 2" : "Passkeys not supported on this device"}
            >
              <Fingerprint className="h-4 w-4" /> Continue with passkey (Sprint 2)
            </Button>
            <Alert variant="default" className="text-xs">
              <AlertDescription>
                Sprint 1 stub auth — any non-empty password is accepted. WebAuthn will replace this in Sprint 2.
              </AlertDescription>
            </Alert>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
